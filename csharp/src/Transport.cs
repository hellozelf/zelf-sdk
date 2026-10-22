using System.Globalization;
using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Zelf;

/// <summary>The response wrapper every Zelf endpoint returns.</summary>
public sealed record Envelope<T>(
    [property: JsonPropertyName("log_id")] string LogId,
    [property: JsonPropertyName("timestamp")] string Timestamp,
    [property: JsonPropertyName("results")] IReadOnlyList<T> Results,
    [property: JsonPropertyName("item_count")] int ItemCount,
    [property: JsonPropertyName("page")] int Page,
    [property: JsonPropertyName("next")] int? Next,
    [property: JsonPropertyName("previous")] int? Previous,
    [property: JsonPropertyName("applied_filters")] JsonElement AppliedFilters);

/// <summary>Settings for a <see cref="ZelfClient"/>.</summary>
public sealed class ZelfClientOptions
{
    /// <summary>The production Zelf API.</summary>
    public const string DefaultBaseUrl = "https://api.hellozelf.com";

    /// <summary>Read when no key is set explicitly.</summary>
    public const string ApiKeyEnvironmentVariable = "ZELF_API_KEY";

    /// <summary>Read when no base URL is set explicitly.</summary>
    public const string BaseUrlEnvironmentVariable = "ZELF_BASE_URL";

    /// <summary>The brand API key. Falls back to ZELF_API_KEY.</summary>
    public string? ApiKey { get; set; }

    public string BaseUrl { get; set; } =
        Environment.GetEnvironmentVariable(BaseUrlEnvironmentVariable) is { Length: > 0 } url
            ? url
            : DefaultBaseUrl;

    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(60);

    public int MaxRetries { get; set; } = 2;

    /// <summary>
    /// Allows non-idempotent requests to be retried. The API publishes no
    /// idempotency key, so a retried create can run twice. Opt in deliberately.
    /// </summary>
    public bool RetryWrites { get; set; }

    public IDictionary<string, string> DefaultHeaders { get; } = new Dictionary<string, string>();

    /// <summary>Supplies the HttpClient used for transport.</summary>
    public HttpClient? HttpClient { get; set; }
}

/// <summary>Carries out the HTTP work: auth, retries, and envelope decoding.</summary>
public sealed class Transport : IDisposable
{
    private static readonly HashSet<HttpStatusCode> RetryStatuses =
    [
        HttpStatusCode.TooManyRequests,
        HttpStatusCode.InternalServerError,
        HttpStatusCode.BadGateway,
        HttpStatusCode.ServiceUnavailable,
        HttpStatusCode.GatewayTimeout,
    ];

    internal static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly HttpClient _http;
    private readonly bool _ownsHttp;
    private readonly string _apiKey;
    private readonly IReadOnlyDictionary<string, string> _headers;

    public string BaseUrl { get; }

    public int MaxRetries { get; }

    public bool RetryWrites { get; }

    public Transport(ZelfClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var key = options.ApiKey ?? Environment.GetEnvironmentVariable(ZelfClientOptions.ApiKeyEnvironmentVariable);
        if (string.IsNullOrEmpty(key))
        {
            throw new ArgumentException(
                $"An API key is required. Set ApiKey or {ZelfClientOptions.ApiKeyEnvironmentVariable}.",
                nameof(options));
        }
        if (options.MaxRetries < 0)
        {
            throw new ArgumentException("MaxRetries must be zero or greater.", nameof(options));
        }

        _apiKey = key;
        _ownsHttp = options.HttpClient is null;
        _http = options.HttpClient ?? new HttpClient { Timeout = options.Timeout };
        // A caller's copy of the API key is dropped whatever its casing, so it
        // cannot be added alongside the client's own.
        _headers = options.DefaultHeaders
            .Where(pair => !string.Equals(pair.Key, "x-api-key", StringComparison.OrdinalIgnoreCase))
            .ToDictionary(pair => pair.Key, pair => pair.Value);
        BaseUrl = options.BaseUrl.TrimEnd('/');
        MaxRetries = options.MaxRetries;
        RetryWrites = options.RetryWrites;
    }

    /// <summary>Never prints the key.</summary>
    public override string ToString() => $"Transport(BaseUrl={BaseUrl}, ApiKey=***)";

    public void Dispose()
    {
        if (_ownsHttp)
        {
            _http.Dispose();
        }
    }

    /// <summary>Substitutes the path parameters, leaving a path relative to the base URL.</summary>
    public static string ResolvePath(string path, IReadOnlyDictionary<string, string> pathParams)
    {
        foreach (var (name, value) in pathParams)
        {
            if (string.IsNullOrEmpty(value))
            {
                throw new ArgumentException($"{name} is required and must not be empty.", nameof(pathParams));
            }
            path = path.Replace("{" + name + "}", Uri.EscapeDataString(value), StringComparison.Ordinal);
        }
        return path;
    }

    public static string BuildQuery(IEnumerable<KeyValuePair<string, string>> pairs)
    {
        var parts = pairs
            .Select(pair => $"{Uri.EscapeDataString(pair.Key)}={Uri.EscapeDataString(pair.Value)}")
            .ToArray();
        return parts.Length == 0 ? string.Empty : "?" + string.Join("&", parts);
    }

    internal static TimeSpan Backoff(int attempt, HttpResponseMessage? response)
    {
        var header = response?.Headers.RetryAfter;
        if (header?.Delta is { } delta)
        {
            return delta > TimeSpan.FromMinutes(1) ? TimeSpan.FromMinutes(1) : delta;
        }
        var ceiling = Math.Min(8000d, 500d * Math.Pow(2, attempt));
        return TimeSpan.FromMilliseconds(ceiling * (0.5 + (Random.Shared.NextDouble() / 2)));
    }

    private bool ShouldRetry(HttpMethod method, HttpResponseMessage? response)
    {
        var idempotent = method == HttpMethod.Get || method == HttpMethod.Head || method == HttpMethod.Options;
        // The API documents no Idempotency-Key header, so a retried write could
        // create a second analysis, vetting, or sync job.
        if (!idempotent && !RetryWrites)
        {
            return false;
        }
        return response is null || RetryStatuses.Contains(response.StatusCode);
    }

    public async Task<Envelope<T>> SendAsync<T>(
        HttpMethod method,
        string path,
        IReadOnlyList<KeyValuePair<string, string>>? query = null,
        object? body = null,
        CancellationToken cancellationToken = default)
    {
        var url = BaseUrl + path + BuildQuery(query ?? []);
        Exception? last = null;

        for (var attempt = 0; attempt <= MaxRetries; attempt++)
        {
            HttpResponseMessage? response = null;
            try
            {
                using var request = new HttpRequestMessage(method, url);
                request.Headers.TryAddWithoutValidation("accept", "application/json");
                request.Headers.TryAddWithoutValidation("user-agent", $"zelf-dotnet/{ZelfClient.Version}");
                foreach (var (name, value) in _headers)
                {
                    request.Headers.TryAddWithoutValidation(name, value);
                }
                // Last, so the client's own key always wins.
                request.Headers.TryAddWithoutValidation("x-api-key", _apiKey);
                if (body is not null)
                {
                    request.Content = new StringContent(
                        JsonSerializer.Serialize(body, Json), Encoding.UTF8, "application/json");
                }

                response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false);
                if (response.IsSuccessStatusCode)
                {
                    return await DecodeAsync<T>(response, cancellationToken).ConfigureAwait(false);
                }
                last = await ZelfApiException.FromResponseAsync(response, cancellationToken).ConfigureAwait(false);
            }
            catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                last = new ZelfTimeoutException();
            }
            catch (HttpRequestException error)
            {
                last = new ZelfConnectionException(error.Message, error);
            }

            if (attempt == MaxRetries || !ShouldRetry(method, response))
            {
                break;
            }
            response?.Dispose();
            await Task.Delay(Backoff(attempt, response), cancellationToken).ConfigureAwait(false);
        }

        throw last ?? new ZelfConnectionException("The request was never sent.");
    }

    private static async Task<Envelope<T>> DecodeAsync<T>(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.StatusCode == HttpStatusCode.NoContent)
        {
            return Empty<T>();
        }
        var raw = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(raw))
        {
            return Empty<T>();
        }
        try
        {
            return JsonSerializer.Deserialize<Envelope<T>>(raw, Json) ?? Empty<T>();
        }
        catch (JsonException error)
        {
            throw new ZelfApiException(
                "The API returned a response that is not a valid envelope.",
                (int)response.StatusCode, null, null, null, error);
        }
    }

    private static Envelope<T> Empty<T>() =>
        new(string.Empty, string.Empty, [], 0, 0, null, null, default);
}

/// <summary>Renders one query value the way the API expects to read it.</summary>
internal static class QueryValue
{
    public static string Format(object value) => value switch
    {
        bool flag => flag ? "true" : "false",
        DateTimeOffset moment => moment.ToString("o", CultureInfo.InvariantCulture),
        IFormattable number => number.ToString(null, CultureInfo.InvariantCulture),
        _ => value.ToString() ?? string.Empty,
    };
}
