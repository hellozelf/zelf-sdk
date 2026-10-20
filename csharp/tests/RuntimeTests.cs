using System.Net;
using System.Text;
using System.Text.Json;
using Xunit;
using Zelf.Webhooks;

namespace Zelf.Tests;

/// <summary>The hand written runtime: transport, errors and webhooks.</summary>
public class RuntimeTests
{
    private const string Row = """
        {"id":"brd_1","title":"ZelfAI","is_primary":true,"keywords":{}}
        """;

    private static string Envelope(string next = "null") => $$"""
        {"log_id":"log_1","timestamp":"2026-01-01T00:00:00Z","applied_filters":{"page":1},
         "results":[{{Row}}],"item_count":1,"page":1,"next":{{next}},"previous":null}
        """;

    [Fact]
    public void ToStringHidesTheKey()
    {
        var options = new ZelfClientOptions { ApiKey = Fixtures.ApiKey, BaseUrl = "https://x" };
        using var transport = new Transport(options);
        Assert.DoesNotContain(Fixtures.ApiKey, transport.ToString());
        Assert.Contains("***", transport.ToString());
    }

    [Fact]
    public void ASuppliedHttpClientIsUsed()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, Envelope(), null));
        using var client = new ZelfClient(new ZelfClientOptions
        {
            ApiKey = Fixtures.ApiKey,
            HttpClient = new HttpClient(stub),
        });
        Assert.NotNull(client.Brands);
    }

    [Fact]
    public async Task AnEmptyPathParameterIsRefused()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, Envelope(), null));
        using var client = Fixtures.Client(stub);
        await Assert.ThrowsAsync<ArgumentException>(() => client.Content.DetailsAsync(""));
    }

    [Fact]
    public async Task AnUnparseableRetryAfterFallsBackToBackoff()
    {
        var stub = new Stub((n, request) => n == 1
            ? (HttpStatusCode.InternalServerError, """{"error":{"code":"INTERNAL_ERROR"}}""", "soon")
            : (HttpStatusCode.OK, Envelope(), null));
        using var client = Fixtures.Client(stub, maxRetries: 1);

        await client.Brands.ListAsync();

        Assert.Equal(2, stub.Requests.Count);
    }

    [Fact]
    public async Task AnEmptyBodyDecodesToAnEmptyEnvelope()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, "   ", null));
        using var client = Fixtures.Client(stub);
        await Assert.ThrowsAsync<ZelfNotFoundException>(() => client.Usage.RetrieveAsync());
    }

    [Fact]
    public async Task ANoContentResponseDecodesToAnEmptyEnvelope()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.NoContent, string.Empty, null));
        using var client = Fixtures.Client(stub);
        await Assert.ThrowsAsync<ZelfNotFoundException>(() => client.Usage.RetrieveAsync());
    }

    [Fact]
    public async Task ABodyThatIsNotJsonIsReported()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, "<html>", null));
        using var client = Fixtures.Client(stub);
        await Assert.ThrowsAsync<ZelfApiException>(() => client.Usage.RetrieveAsync());
    }

    [Fact]
    public async Task AnErrorBodyThatIsNotJsonStillRaises()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.InternalServerError, "<html>", null));
        using var client = Fixtures.Client(stub);
        await Assert.ThrowsAsync<ZelfInternalServerException>(() => client.Usage.RetrieveAsync());
    }

    [Theory]
    [InlineData(HttpStatusCode.BadRequest, typeof(ZelfBadRequestException))]
    [InlineData(HttpStatusCode.Unauthorized, typeof(ZelfAuthenticationException))]
    [InlineData(HttpStatusCode.Forbidden, typeof(ZelfPermissionDeniedException))]
    [InlineData(HttpStatusCode.NotFound, typeof(ZelfNotFoundException))]
    [InlineData(HttpStatusCode.NotAcceptable, typeof(ZelfNotAcceptableException))]
    [InlineData(HttpStatusCode.Conflict, typeof(ZelfConflictException))]
    [InlineData(HttpStatusCode.TooManyRequests, typeof(ZelfRateLimitException))]
    [InlineData(HttpStatusCode.ServiceUnavailable, typeof(ZelfServiceUnavailableException))]
    [InlineData((HttpStatusCode)418, typeof(ZelfApiException))]
    public async Task EveryStatusMapsToItsType(HttpStatusCode status, Type expected)
    {
        const string body = """
            {"log_id":"log_1","error":{"code":"X","message":"m","details":{"field":"bad"}}}
            """;
        var stub = new Stub((n, request) => (status, body, null));
        using var client = Fixtures.Client(stub);

        var error = await Assert.ThrowsAnyAsync<ZelfApiException>(
            () => client.Usage.RetrieveAsync());

        Assert.IsType(expected, error);
        Assert.Equal((int)status, error.Status);
        Assert.Contains("log_id=log_1", error.ToString());
        Assert.NotNull(error.Details);
    }

    [Fact]
    public void ConnectionAndTimeoutErrorsCarryTheirMessage()
    {
        var connection = new ZelfConnectionException("socket closed", new IOException("boom"));
        Assert.Contains("socket closed", connection.Message);
        Assert.NotNull(new ZelfTimeoutException().Message);
    }

    [Fact]
    public void AnApiErrorWithoutALogIdStillPrints()
    {
        var error = new ZelfApiException("m", 500, null, null, null);
        Assert.DoesNotContain("log_id", error.ToString());
    }

    [Fact]
    public async Task AConnectionFailureIsTyped()
    {
        using var client = new ZelfClient(new ZelfClientOptions
        {
            ApiKey = Fixtures.ApiKey,
            BaseUrl = "http://127.0.0.1:1",
            MaxRetries = 0,
        });
        await Assert.ThrowsAsync<ZelfConnectionException>(() => client.Usage.RetrieveAsync());
    }

    private static string Sign(byte[] payload, long timestamp, string secret)
    {
        using var mac = new System.Security.Cryptography.HMACSHA256(
            Encoding.UTF8.GetBytes(secret));
        var signed = Encoding.UTF8.GetBytes($"{timestamp}.").Concat(payload).ToArray();
        return $"t={timestamp},v1={Convert.ToHexString(mac.ComputeHash(signed)).ToLowerInvariant()}";
    }

    private const string Secret = "whsec_abcdef0123456789";

    private static byte[] Push(string deliveryMode, string data) => Encoding.UTF8.GetBytes($$"""
        {"id":"whd_1","type":"content.snapshot","subscription_id":"whs_1",
         "delivered_at":1718000000,"livemode":true,"resource":"content",
         "delivery_mode":"{{deliveryMode}}","data":{{data}}}
        """);

    [Fact]
    public void AnEventExposesEveryAccessor()
    {
        var payload = Push("inline",
            """{"item_count":1,"items":[{"id":"con_1"}],"statistics":{"post_count":1}}""");
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();

        var webhookEvent = Webhook.Parse(payload, Sign(payload, now, Secret), [Secret]);

        Assert.Equal("whd_1", webhookEvent.Id);
        Assert.Equal("content.snapshot", webhookEvent.Type);
        Assert.Equal(EventType.ContentSnapshot, webhookEvent.Kind);
        Assert.Equal("inline", webhookEvent.DeliveryMode);
        Assert.Equal(1, webhookEvent.ItemCount);
        Assert.NotNull(webhookEvent.Statistics);
        Assert.Single(webhookEvent.Items);
        Assert.Contains("WebhookEvent", webhookEvent.ToString());
        Assert.Equal("content.snapshot", EventTypes.ToWire(EventType.ContentSnapshot));
    }

    [Fact]
    public void ABodyThatIsNotAJsonObjectIsRefused()
    {
        var payload = Encoding.UTF8.GetBytes("[1,2,3]");
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Verify(payload, Sign(payload, now, Secret), [Secret]));
    }

    [Fact]
    public void ABodyThatIsNotJsonIsRefused()
    {
        var payload = Encoding.UTF8.GetBytes("not json");
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Verify(payload, Sign(payload, now, Secret), [Secret]));
    }

    [Fact]
    public void ASignatureWithNoSecretsIsRefused()
    {
        var payload = Push("inline", """{"item_count":0}""");
        Assert.Throws<ArgumentException>(() => Webhook.Verify(payload, "t=1,v1=ab", []));
    }

    [Fact]
    public void AMalformedSignatureIsRefused()
    {
        var payload = Push("inline", """{"item_count":0}""");
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Verify(payload, "v1=abcd", [Secret]));
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Verify(payload, "t=soon,v1=abcd", [Secret]));
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Verify(payload, string.Empty, [Secret]));
    }

    [Fact]
    public async Task RowsDownloadsAndVerifiesTheManifest()
    {
        var file = Encoding.UTF8.GetBytes("{\"id\":\"con_1\"}\n\n{\"id\":\"con_2\"}\n");
        var digest = Convert.ToHexString(
            System.Security.Cryptography.SHA256.HashData(file)).ToLowerInvariant();

        var handler = new Stub((n, request) => request.RequestUri!.AbsolutePath switch
        {
            "/broken" => (HttpStatusCode.InternalServerError, string.Empty, null),
            _ => (HttpStatusCode.OK, Encoding.UTF8.GetString(file), null),
        });
        using var http = new HttpClient(handler);

        var payload = Push("manifest", $$"""
            {"item_count":2,"files":[{"download_url":"https://files.test/ok","sha256":"{{digest}}"}]}
            """);
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var ok = Webhook.Parse(payload, Sign(payload, now, Secret), [Secret]);

        var seen = new List<string>();
        await foreach (var row in ok.RowsAsync(http))
        {
            seen.Add(row.GetProperty("id").GetString()!);
        }
        Assert.Equal(["con_1", "con_2"], seen);

        var tampered = Push("manifest", $$"""
            {"item_count":1,"files":[{"download_url":"https://files.test/ok","sha256":"{{new string('0', 64)}}"}]}
            """);
        var bad = Webhook.Parse(tampered, Sign(tampered, now, Secret), [Secret]);
        await Assert.ThrowsAsync<WebhookVerificationException>(async () =>
        {
            await foreach (var _ in bad.RowsAsync(http))
            {
            }
        });

        var unsigned = Push("manifest", """
            {"item_count":2,"files":[{"download_url":"https://files.test/ok","sha256":""}]}
            """);
        var unchecked_ = Webhook.Parse(unsigned, Sign(unsigned, now, Secret), [Secret]);
        await Assert.ThrowsAsync<WebhookVerificationException>(async () =>
        {
            await foreach (var _ in unchecked_.RowsAsync(http))
            {
            }
        });

        var waived = new List<string>();
        await foreach (var row in unchecked_.RowsAsync(http, verifyChecksum: false))
        {
            waived.Add(row.GetProperty("id").GetString()!);
        }
        Assert.Equal(["con_1", "con_2"], waived);

        var broken = Push("manifest", """
            {"item_count":1,"files":[{"download_url":"https://files.test/broken","sha256":""}]}
            """);
        var failing = Webhook.Parse(broken, Sign(broken, now, Secret), [Secret]);
        await Assert.ThrowsAsync<WebhookVerificationException>(async () =>
        {
            await foreach (var _ in failing.RowsAsync(http))
            {
            }
        });
    }

    [Fact]
    public void NegativeRetriesAreRefused()
    {
        Assert.Throws<ArgumentException>(() => new ZelfClient(new ZelfClientOptions
        {
            ApiKey = Fixtures.ApiKey,
            MaxRetries = -1,
        }));
    }

    [Fact]
    public async Task APathWithNoParametersIsLeftAlone()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, Envelope(), null));
        using var client = Fixtures.Client(stub);
        await client.Brands.ListAsync();
        Assert.Equal("/api/v1/brands/", stub.Requests[0].RequestUri!.AbsolutePath);
    }

    [Fact]
    public async Task ATimeoutIsTyped()
    {
        var stub = new Stub((n, request) => throw new TaskCanceledException("slow"));
        using var client = Fixtures.Client(stub);
        await Assert.ThrowsAsync<ZelfTimeoutException>(() => client.Usage.RetrieveAsync());
    }

    [Fact]
    public void APagePrintsItsShape()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, Envelope(), null));
        using var client = Fixtures.Client(stub);
        var page = client.Brands.ListAsync().GetAwaiter().GetResult();
        Assert.Contains("Page", page.ToString());
    }

    [Fact]
    public void AnUnknownEventTypeHasNoWireValue()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => EventTypes.ToWire((EventType)999));
    }

    [Fact]
    public void ANonHexDigestIsSkipped()
    {
        var payload = Push("inline", """{"item_count":0}""");
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Verify(payload, $"t={now},v1=nothex!!", [Secret]));
    }

    [Fact]
    public async Task DefaultHeadersReachTheRequest()
    {
        var stub = new Stub((n, request) => (HttpStatusCode.OK, Envelope(), null));
        var options = new ZelfClientOptions
        {
            ApiKey = Fixtures.ApiKey,
            BaseUrl = "https://api.hellozelf.com",
            MaxRetries = 0,
            HttpClient = new HttpClient(stub),
        };
        options.DefaultHeaders["X-Trace"] = "abc";
        using var client = new ZelfClient(options);

        await client.Usage.RetrieveAsync();

        Assert.Equal("abc", stub.Requests[0].Headers.GetValues("X-Trace").Single());
    }

    [Fact]
    public void DeliveryModesAreListed()
    {
        Assert.Contains(WebhookPushDeliveryMode.Manifest, WebhookPushDeliveryMode.All);
        Assert.Contains(WebhookPushDeliveryMode.Inline, WebhookPushDeliveryMode.All);
    }
}
