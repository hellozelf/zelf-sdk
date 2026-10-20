using System.Net;
using Xunit;

namespace Zelf.Tests;

public class PagingTests
{
    /// <summary>Serves `count` pages of one row each.</summary>
    private static Stub Paged(int count) => new((n, _) =>
    {
        var next = n < count ? n + 1 : (int?)null;
        var body = Fixtures.Envelope(
            $"[{Fixtures.ContentRow($"con_{n}").GetRawText()}]", n, next?.ToString() ?? "null");
        return (HttpStatusCode.OK, body, null);
    });

    private static async Task<(List<string> Ids, int Calls)> Walk(int pages, PageLimits limits)
    {
        var stub = Paged(pages);
        using var client = Fixtures.Client(stub);
        var page = await client.Content.ListAsync(new ContentListParams());

        var ids = new List<string>();
        await foreach (var item in page.AutoPagingAsync(limits))
        {
            ids.Add(item.Id);
        }
        return (ids, stub.Requests.Count);
    }

    [Fact]
    public async Task MaxPagesStopsTheWalkEarly()
    {
        var (ids, calls) = await Walk(5, PageLimits.Pages(3));

        Assert.Equal(["con_1", "con_2", "con_3"], ids);
        Assert.Equal(3, calls);
    }

    [Fact]
    public async Task MaxPagesOfOneMakesNoFurtherRequest()
    {
        var (ids, calls) = await Walk(5, PageLimits.Pages(1));

        Assert.Equal(["con_1"], ids);
        Assert.Equal(1, calls);
    }

    [Fact]
    public async Task MaxItemsStopsBeforeAPageItDoesNotNeed()
    {
        var (ids, calls) = await Walk(5, PageLimits.Items(2));

        Assert.Equal(["con_1", "con_2"], ids);
        Assert.Equal(2, calls);
    }

    [Fact]
    public async Task NoLimitWalksEverything()
    {
        var (ids, calls) = await Walk(4, PageLimits.None);

        Assert.Equal(["con_1", "con_2", "con_3", "con_4"], ids);
        Assert.Equal(4, calls);
    }

    [Fact]
    public async Task PagesHonoursMaxPages()
    {
        var stub = Paged(5);
        using var client = Fixtures.Client(stub);
        var page = await client.Content.ListAsync(new ContentListParams());

        var numbers = new List<int>();
        await foreach (var seen in page.PagesAsync(PageLimits.Pages(2)))
        {
            numbers.Add(seen.Number);
        }

        Assert.Equal([1, 2], numbers);
        Assert.Equal(2, stub.Requests.Count);
    }

    [Fact]
    public async Task ALimitBelowOneIsRejected()
    {
        var stub = Paged(3);
        using var client = Fixtures.Client(stub);
        var page = await client.Content.ListAsync(new ContentListParams());

        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(async () =>
        {
            await foreach (var _ in page.AutoPagingAsync(new PageLimits { MaxPages = 0 }))
            {
                // unreachable
            }
        });
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(async () =>
        {
            await foreach (var _ in page.AutoPagingAsync(new PageLimits { MaxItems = 0 }))
            {
                // unreachable
            }
        });
    }
}
