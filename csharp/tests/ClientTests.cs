using Xunit;
using System.Net;
using System.Text.Json;

namespace Zelf.Tests;

public class ClientTests
{
    private static Stub Ok(string body) =>
        new((_, _) => (HttpStatusCode.OK, body, null));

    [Fact]
    public async Task ListReturnsATypedPage()
    {
        var stub = Ok(Fixtures.Envelope($"[{Fixtures.ContentRow().GetRawText()}]"));
        using var client = Fixtures.Client(stub);

        var page = await client.Content.ListAsync(new ContentListParams { Search = "running shoes" });

        Assert.Single(page.Results);
        Assert.Equal("con_1", page.Results[0].Id);
        Assert.Equal(184230, page.Results[0].ViewCount);
        Assert.Equal("log_1", page.LogId);
        Assert.False(page.HasNext);
        Assert.Contains("search=running%20shoes", stub.Requests[0].RequestUri!.Query);
    }

    [Fact]
    public async Task TheApiKeyTravelsInAHeaderNeverTheUrl()
    {
        var stub = Ok(Fixtures.Envelope("""[{"plan":"pro"}]"""));
        using var client = Fixtures.Client(stub);

        await client.Usage.RetrieveAsync();

        var request = stub.Requests[0];
        Assert.Equal(Fixtures.ApiKey, request.Headers.GetValues("x-api-key").Single());
        Assert.DoesNotContain(Fixtures.ApiKey, request.RequestUri!.ToString());
        Assert.StartsWith("zelf-dotnet/", request.Headers.GetValues("user-agent").Single());
    }

    [Fact]
    public void TheApiKeyStaysOutOfToString()
    {
        using var client = new ZelfClient(Fixtures.ApiKey);

        Assert.DoesNotContain(Fixtures.ApiKey, client.ToString());
        Assert.Contains("***", client.ToString());
    }

    [Fact]
    public void AMissingKeyFailsBeforeAnyRequest()
    {
        Environment.SetEnvironmentVariable("ZELF_API_KEY", null);

        Assert.Throws<ArgumentException>(() => new ZelfClient(new ZelfClientOptions()));
    }

    [Fact]
    public async Task ASingleReadThatMatchesNothingIsANotFound()
    {
        var stub = Ok(Fixtures.Envelope("[]"));
        using var client = Fixtures.Client(stub);

        var error = await Assert.ThrowsAsync<ZelfNotFoundException>(
            () => client.Content.DetailsAsync("con_missing"));

        Assert.Equal(404, error.Status);
        Assert.Contains("No Content matched", error.Message);
    }

    [Fact]
    public async Task PathParametersAreEscaped()
    {
        var stub = Ok(Fixtures.Envelope($"[{Fixtures.ContentRow().GetRawText()}]"));
        using var client = Fixtures.Client(stub);

        await client.Content.DetailsAsync("con/../../admin");

        Assert.Contains("con%2F..%2F..%2Fadmin", stub.Requests[0].RequestUri!.AbsolutePath);
    }

    [Fact]
    public async Task AnEmptyPathParameterIsRejected()
    {
        var stub = Ok(Fixtures.Envelope("[]"));
        using var client = Fixtures.Client(stub);

        await Assert.ThrowsAsync<ArgumentException>(() => client.Content.DetailsAsync(""));
    }

    [Fact]
    public async Task ErrorsMapToTypedClasses()
    {
        var stub = new Stub((_, _) => (HttpStatusCode.Unauthorized,
            """{"log_id":"log_1","error":{"code":"INVALID_API_KEY","message":"Nope.","details":{}}}""", null));
        using var client = Fixtures.Client(stub);

        var error = await Assert.ThrowsAsync<ZelfAuthenticationException>(
            () => client.Content.ListAsync(new ContentListParams()));

        Assert.Equal(401, error.Status);
        Assert.Equal(ZelfErrorCode.InvalidApiKey, error.Code);
        Assert.Equal("log_1", error.LogId);
        Assert.IsAssignableFrom<ZelfApiException>(error);
    }

    [Fact]
    public async Task ARateLimitedReadIsRetried()
    {
        var stub = new Stub((n, _) => n == 1
            ? (HttpStatusCode.TooManyRequests, """{"error":{"code":"RATE_LIMIT_EXCEEDED"}}""", "0")
            : (HttpStatusCode.OK, Fixtures.Envelope($"[{Fixtures.ContentRow().GetRawText()}]"), null));
        using var client = Fixtures.Client(stub, maxRetries: 2);

        var page = await client.Content.ListAsync(new ContentListParams());

        Assert.Single(page.Results);
        Assert.Equal(2, stub.Requests.Count);
    }

    [Fact]
    public async Task AWriteIsNotRetriedByDefault()
    {
        var stub = new Stub((_, _) => (HttpStatusCode.ServiceUnavailable,
            """{"error":{"code":"SERVICE_UNAVAILABLE"}}""", null));
        using var client = Fixtures.Client(stub, maxRetries: 3);

        await Assert.ThrowsAsync<ZelfServiceUnavailableException>(
            () => client.CreatorSync.CreateAsync(
                new CreatorSyncCreateParams { ProfileUrl = "https://www.tiktok.com/@zelf" }));

        // The API has no idempotency key, so a retried create could run twice.
        Assert.Single(stub.Requests);
    }

    [Fact]
    public async Task AClientErrorIsNeverRetried()
    {
        var stub = new Stub((_, _) => (HttpStatusCode.BadRequest,
            """{"error":{"code":"VALIDATION_ERROR"}}""", null));
        using var client = Fixtures.Client(stub, maxRetries: 3);

        await Assert.ThrowsAsync<ZelfBadRequestException>(
            () => client.Content.ListAsync(new ContentListParams()));

        Assert.Single(stub.Requests);
    }

    [Fact]
    public async Task RequestBodiesAreSentAsJson()
    {
        var stub = new Stub((_, _) => (HttpStatusCode.Created, Fixtures.Envelope("""[{"id":"ana_1"}]"""), null));
        using var client = Fixtures.Client(stub);

        await client.AiAnalysis.CreateAsync(new AiAnalysisCreateParams
        {
            Name = "Launch",
            Topic = "sentiment",
            ContentFilters = new ContentFilterInputRequest { Search = "zelf" },
        });

        var sent = JsonDocument.Parse(stub.Bodies[0]).RootElement;
        Assert.Equal("Launch", sent.GetProperty("name").GetString());
        Assert.Equal("sentiment", sent.GetProperty("topic").GetString());
    }

    [Fact]
    public async Task ArrayQueryParametersRepeatTheKey()
    {
        var stub = Ok(Fixtures.Envelope("[]"));
        using var client = Fixtures.Client(stub);

        await client.Content.ListAsync(new ContentListParams
        {
            Platform = ["instagram", "tiktok"],
            IsOwned = true,
        });

        var query = stub.Requests[0].RequestUri!.Query;
        Assert.Contains("platform=instagram", query);
        Assert.Contains("platform=tiktok", query);
        Assert.Contains("is_owned=true", query);
        Assert.DoesNotContain("brand_id", query);
    }
}
