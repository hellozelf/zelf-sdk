using System.Net;
using System.Text;
using System.Text.Json;

namespace Zelf.Tests;

/// <summary>Answers requests from a queue and records what was asked.</summary>
public sealed class Stub : HttpMessageHandler
{
    private readonly Func<int, HttpRequestMessage, (HttpStatusCode Status, string Body, string? RetryAfter)> _responder;

    public Stub(Func<int, HttpRequestMessage, (HttpStatusCode, string, string?)> responder)
    {
        _responder = responder;
    }

    public List<HttpRequestMessage> Requests { get; } = [];

    public List<string> Bodies { get; } = [];

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests.Add(request);
        Bodies.Add(request.Content is null
            ? string.Empty
            : await request.Content.ReadAsStringAsync(cancellationToken));

        var (status, body, retryAfter) = _responder(Requests.Count, request);
        var response = new HttpResponseMessage(status)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        if (retryAfter is not null)
        {
            response.Headers.TryAddWithoutValidation("Retry-After", retryAfter);
        }
        return response;
    }
}

public static class Fixtures
{
    public const string ApiKey = "sk_test_not_a_real_key";

    private static readonly JsonDocument Document =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(
            AppContext.BaseDirectory, "..", "..", "..", "..", "..", "fixtures.json")));

    /// <summary>The spec's own published example for content.list.</summary>
    public static JsonElement ContentRow(string id = "con_1")
    {
        var row = Document.RootElement
            .GetProperty("envelopes").GetProperty("content_list")
            .GetProperty("results")[0];
        var node = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(row.GetRawText())!;
        node["id"] = JsonSerializer.SerializeToElement(id);
        return JsonSerializer.SerializeToElement(node);
    }

    public static string Envelope(string results, int page = 1, string next = "null") => $$"""
        {"log_id":"log_1","timestamp":"2026-01-01T00:00:00Z","applied_filters":{"page":{{page}}},
         "results":{{results}},"item_count":1,"page":{{page}},"next":{{next}},"previous":null}
        """;

    /// <summary>The envelope the fixtures publish for one operation.</summary>
    public static string EnvelopeFor(string operation) =>
        Document.RootElement.GetProperty("envelopes")
            .GetProperty(operation.Replace(".", "_")).GetRawText();

    /// <summary>One synthesized sample per model.</summary>
    public static JsonElement Models() => Document.RootElement.GetProperty("models");

    public static ZelfClient Client(Stub stub, int maxRetries = 0, bool retryWrites = false) =>
        new(new ZelfClientOptions
        {
            ApiKey = ApiKey,
            BaseUrl = "https://api.hellozelf.com",
            MaxRetries = maxRetries,
            RetryWrites = retryWrites,
            HttpClient = new HttpClient(stub),
        });
}
