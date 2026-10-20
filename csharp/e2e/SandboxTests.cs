using Xunit;
using Zelf;

namespace Zelf.E2E;

/// <summary>The six steps every language runs against the live sandbox.</summary>
public class SandboxTests
{
    private static readonly string Base =
        Environment.GetEnvironmentVariable("ZELF_BASE_URL") ?? "https://sandbox-api.hellozelf.com";

    private static readonly string Key =
        Environment.GetEnvironmentVariable("ZELF_API_KEY") ?? "sk_zelf_sandbox_demo";

    private static ZelfClient Client(Action<ZelfClientOptions>? configure = null)
    {
        var options = new ZelfClientOptions { ApiKey = Key, BaseUrl = Base, Timeout = TimeSpan.FromSeconds(30) };
        configure?.Invoke(options);
        return new ZelfClient(options);
    }

    [Fact]
    public async Task UsageDecodes()
    {
        using var client = Client();
        Assert.NotNull(await client.Usage.RetrieveAsync());
    }

    [Fact]
    public async Task APageDecodesEveryRow()
    {
        using var client = Client();
        var page = await client.Content.ListAsync(new ContentListParams { PageSize = 2 });

        Assert.Equal(2, page.ItemCount);
        Assert.All(page.Results, row => Assert.StartsWith("con_", row.Id));
    }

    [Fact]
    public async Task AutoPagingStopsAtTheBound()
    {
        using var client = Client();
        var page = await client.Content.ListAsync(new ContentListParams { PageSize = 2 });

        var rows = new List<object>();
        await foreach (var row in page.AutoPagingAsync(PageLimits.Pages(2)))
        {
            rows.Add(row);
        }
        Assert.Equal(4, rows.Count);
    }

    [Fact]
    public async Task ABadKeyRaisesTheTypedError()
    {
        using var bad = Client(options =>
        {
            options.ApiKey = "sk_zelf_" + new string('9', 64);
            options.MaxRetries = 0;
        });

        var error = await Assert.ThrowsAsync<ZelfAuthenticationException>(
            () => bad.Usage.RetrieveAsync());

        Assert.Equal(401, error.Status);
        Assert.Equal("INVALID_API_KEY", error.Code);
    }

    [Fact]
    public async Task ARateLimitIsRetriedThenSurfaced()
    {
        using var throttled = Client(options =>
        {
            options.MaxRetries = 1;
            options.DefaultHeaders["x-sandbox-force-error"] = "RATE_LIMIT_EXCEEDED";
        });

        var error = await Assert.ThrowsAsync<ZelfRateLimitException>(
            () => throttled.Usage.RetrieveAsync());

        Assert.Equal(429, error.Status);
    }

    [Fact]
    public async Task EventTypesAreListed()
    {
        using var client = Client();
        var events = await client.Webhooks.ListEventsAsync();
        Assert.NotEmpty(events);
    }
}
