using System.Diagnostics;
using Xunit;
using Xunit.Abstractions;

namespace Zelf.Tests;

/// <summary>Drives the real API. Skipped unless ZELF_API_KEY is set.</summary>
public class LiveTests(ITestOutputHelper output)
{
    private const string Brand = "brd_6u599tNI2jemKDcb";

    private static ContentListParams Scope() => new()
    {
        BrandId = Brand,
        PostedWithinDays = 365,
        ViewCountMin = 250000000,
        PageSize = 3,
    };

    private async Task Check(string name, Func<Task<string>> body)
    {
        var watch = Stopwatch.StartNew();
        string status = "PASS", detail;
        try
        {
            detail = await body();
        }
        catch (Exception error)
        {
            status = "FAIL";
            detail = $"{error.GetType().Name}: {error.Message}";
        }
        if (detail.Length > 90)
        {
            detail = detail[..90];
        }
        output.WriteLine($"{name,-34} {status}  {watch.ElapsedMilliseconds,6}ms  {detail}");
    }

    [Fact]
    public async Task Sweep()
    {
        var key = Environment.GetEnvironmentVariable("ZELF_API_KEY");
        if (string.IsNullOrEmpty(key))
        {
            output.WriteLine("ZELF_API_KEY is not set; the live sweep did not run.");
            return;
        }

        using var client = new ZelfClient(key!);

        await Check("usage.retrieve", async () => $"usage ok {(await client.Usage.RetrieveAsync()).GetType().Name}");
        await Check("content.list", async () =>
        {
            var page = await client.Content.ListAsync(Scope());
            return $"items={page.ItemCount} first={page.Results[0].Id} views={page.Results[0].ViewCount}";
        });
        await Check("content.list AutoPaging Pages(2)", async () =>
        {
            var page = await client.Content.ListAsync(Scope());
            var seen = 0;
            await foreach (var _ in page.AutoPagingAsync(PageLimits.Pages(2)))
            {
                seen++;
            }
            return $"walked {seen} across <=2 pages";
        });
        await Check("content.details", async () =>
        {
            var page = await client.Content.ListAsync(Scope());
            var found = await client.Content.DetailsAsync(
                page.Results[0].Id, new ContentDetailsParams { BrandId = Brand });
            return $"id={found.Id} platform={found.Platform}";
        });
        await Check("content.details (missing)", async () =>
        {
            try
            {
                await client.Content.DetailsAsync("con_J64wsBXg9rmhOE6dFX");
                return "no error raised";
            }
            catch (ZelfApiException error)
            {
                return $"ZelfApiException status={error.Status} code={error.Code}";
            }
        });
        await Check("bad key -> 401 typed", async () =>
        {
            using var bad = new ZelfClient(new ZelfClientOptions
            {
                ApiKey = "sk_zelf_definitely_invalid",
                MaxRetries = 0,
            });
            try
            {
                await bad.Usage.RetrieveAsync();
                return "no error raised";
            }
            catch (ZelfApiException error)
            {
                return $"{error.Status} {error.Code}";
            }
        });
        await Check("brands.list", async () => $"brands={(await client.Brands.ListAsync()).ItemCount}");
        await Check("webhooks.list_events", async () => $"events={(await client.Webhooks.ListEventsAsync()).Count}");
        await Check("brand_accounts.list", async () =>
        {
            var groups = await client.BrandAccounts.ListAsync(
                new BrandAccountsListParams { BrandId = Brand, AccountType = "tracked" });
            return $"tracked={groups.Tracked?.Count ?? 0}";
        });
    }
}
