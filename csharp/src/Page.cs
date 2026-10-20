using System.Text.Json;

namespace Zelf;

/// <summary>Bounds how far a walk over the remaining pages goes.</summary>
public sealed record PageLimits
{
    /// <summary>Walk everything.</summary>
    public static readonly PageLimits None = new();

    /// <summary>
    /// Stop after this many pages, counting the one already in hand. A value
    /// of 1 makes no further request.
    /// </summary>
    public int? MaxPages { get; init; }

    /// <summary>
    /// Stop once this many items have been visited, so no page is requested
    /// that is not needed to reach the count.
    /// </summary>
    public int? MaxItems { get; init; }

    public static PageLimits Pages(int count) => new() { MaxPages = count };

    public static PageLimits Items(int count) => new() { MaxItems = count };

    internal void Validate()
    {
        if (MaxPages is < 1 || MaxItems is < 1)
        {
            throw new ArgumentOutOfRangeException(
                nameof(MaxPages), "MaxPages and MaxItems need a value of 1 or greater.");
        }
    }
}

/// <summary>
/// One page of results, plus the envelope metadata that came with it.
/// The page keeps the request that produced it, so the next page is fetched by
/// re-issuing that request with a new page value.
/// </summary>
public sealed class Page<T>
{
    private readonly Transport _transport;
    private readonly string _path;
    private readonly IReadOnlyList<KeyValuePair<string, string>> _query;

    internal Page(
        Envelope<T> envelope,
        Transport transport,
        string path,
        IReadOnlyList<KeyValuePair<string, string>> query)
    {
        Results = envelope.Results ?? [];
        LogId = envelope.LogId;
        Number = envelope.Page;
        ItemCount = envelope.ItemCount;
        Next = envelope.Next;
        Previous = envelope.Previous;
        AppliedFilters = envelope.AppliedFilters;
        _transport = transport;
        _path = path;
        _query = query;
    }

    public IReadOnlyList<T> Results { get; }

    public string LogId { get; }

    public int Number { get; }

    public int ItemCount { get; }

    public int? Next { get; }

    public int? Previous { get; }

    public JsonElement AppliedFilters { get; }

    public bool HasNext => Next is not null;

    public override string ToString() =>
        $"Page(Number={Number}, ItemCount={ItemCount}, HasNext={HasNext})";

    /// <summary>The page after this one, or null when there is none.</summary>
    public async Task<Page<T>?> NextPageAsync(CancellationToken cancellationToken = default)
    {
        if (Next is not { } number)
        {
            return null;
        }
        var query = _query
            .Where(pair => pair.Key != "page")
            .Append(new KeyValuePair<string, string>("page", number.ToString()))
            .ToList();
        var envelope = await _transport
            .SendAsync<T>(HttpMethod.Get, _path, query, null, cancellationToken)
            .ConfigureAwait(false);
        return new Page<T>(envelope, _transport, _path, query);
    }

    /// <summary>Yield this page and the ones after it.</summary>
    public async IAsyncEnumerable<Page<T>> PagesAsync(
        PageLimits? limits = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        limits ??= PageLimits.None;
        limits.Validate();
        var current = this;
        var seen = 0;
        while (current is not null)
        {
            yield return current;
            seen++;
            if (limits.MaxPages is { } max && seen >= max)
            {
                yield break;
            }
            current = await current.NextPageAsync(cancellationToken).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Walk the remaining pages, yielding one item at a time. Either limit
    /// stops the walk, so no page is requested once enough items are in hand.
    /// </summary>
    public async IAsyncEnumerable<T> AutoPagingAsync(
        PageLimits? limits = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        limits ??= PageLimits.None;
        limits.Validate();
        var produced = 0;
        await foreach (var page in PagesAsync(limits, cancellationToken).ConfigureAwait(false))
        {
            foreach (var item in page.Results)
            {
                yield return item;
                produced++;
                if (limits.MaxItems is { } max && produced >= max)
                {
                    yield break;
                }
            }
        }
    }
}

internal static class Envelopes
{
    /// <summary>
    /// Take the single row out of the envelope. Reads that match nothing come
    /// back as 200 with an empty results array rather than a 404, so the empty
    /// case becomes a not found error.
    /// </summary>
    public static T One<T>(Envelope<T> envelope, string what)
    {
        if (envelope.Results is null || envelope.Results.Count == 0)
        {
            throw new ZelfNotFoundException(
                $"No {what} matched the request.", 404, "NOT_FOUND", null, envelope.LogId);
        }
        return envelope.Results[0];
    }

    public static IReadOnlyList<T> Rows<T>(Envelope<T> envelope) => envelope.Results ?? [];
}
