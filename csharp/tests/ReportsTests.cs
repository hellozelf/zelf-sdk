using System.Text;
using System.Text.Json;
using Xunit;

namespace Zelf.Tests;

/// <summary>Downloaded reports decode softly through <see cref="ZelfReports"/>.</summary>
public class ReportsTests
{
    private static readonly Dictionary<string, Type> Types = new()
    {
        ["AiAnalysisReport"] = typeof(AiAnalysisReport),
        ["AdvancedAiAnalysisReport"] = typeof(AdvancedAiAnalysisReport),
        ["CreatorVettingReport"] = typeof(CreatorVettingReport),
    };

    private static JsonElement Reports => Fixtures.Reports();

    [Fact]
    public void EveryMalformedReportCaseDecodes()
    {
        foreach (var report in Reports.EnumerateObject())
        {
            foreach (var kase in report.Value.EnumerateObject())
            {
                var decoded = JsonSerializer.Deserialize(
                    kase.Value.GetRawText(), Types[report.Name], ZelfReports.Options);
                Assert.NotNull(decoded);
            }
        }
    }

    [Fact]
    public async Task DecimalRoundsToNearestWhole()
    {
        var document = Reports.GetProperty("AdvancedAiAnalysisReport").GetProperty("decimals").GetRawText();
        using var stream = new MemoryStream(Encoding.UTF8.GetBytes(document));
        var report = await ZelfReports.DecodeAsync<AdvancedAiAnalysisReport>(stream);
        Assert.Equal(13L, report!.Summary!.Videos);
        Assert.Equal(13L, report.TopCreators![0].Posts);
    }

    [Fact]
    public void WholeNumbersNullsAndMissingFieldsRead()
    {
        var summary = ZelfReports.Decode<AdvancedSummary>(
            """{"videos": 9007199254740993, "creators": null, "total_views": -2.5}""")!;
        Assert.Equal(9007199254740993L, summary.Videos);
        Assert.Null(summary.Creators);
        Assert.Equal(-3L, summary.TotalViews);
        Assert.Null(summary.TotalLikes);
        Assert.Contains("\"videos\":9007199254740993", JsonSerializer.Serialize(summary, ZelfReports.Options));
    }

    [Fact]
    public void TextInAWholeNumberFieldStillFails()
    {
        Assert.Throws<JsonException>(
            () => ZelfReports.Decode<AdvancedSummary>("""{"videos": "many"}"""));
    }
}
