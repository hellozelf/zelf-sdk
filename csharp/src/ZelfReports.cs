using System.Text.Json;
using System.Text.Json.Serialization;

namespace Zelf;

/// <summary>
/// Decodes a downloaded report: the JSON behind a run's <c>result.download_url</c>,
/// as <see cref="AiAnalysisReport"/>, <see cref="AdvancedAiAnalysisReport"/> or
/// <see cref="CreatorVettingReport"/>.
/// </summary>
/// <remarks>
/// Reports are written by the AI pipeline, so a field can be null, missing, or a
/// decimal where a whole number is expected. None of those fail the decode: a
/// missing or null field reads as null, and a decimal reads as the nearest whole
/// number.
/// </remarks>
public static class ZelfReports
{
    /// <summary>The serializer options reports are decoded with.</summary>
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new LenientInt64Converter() },
    };

    /// <summary>Decodes a report from its JSON text.</summary>
    public static T? Decode<T>(string json) => JsonSerializer.Deserialize<T>(json, Options);

    /// <summary>Decodes a report from a stream, such as the download response body.</summary>
    public static ValueTask<T?> DecodeAsync<T>(Stream json, CancellationToken cancellationToken = default) =>
        JsonSerializer.DeserializeAsync<T>(json, Options, cancellationToken);
}

/// <summary>Reads a whole number, or a decimal rounded to the nearest whole number.</summary>
internal sealed class LenientInt64Converter : JsonConverter<long>
{
    public override long Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        return reader.TryGetInt64(out var whole)
            ? whole
            : (long)Math.Round(reader.GetDouble(), MidpointRounding.AwayFromZero);
    }

    public override void Write(Utf8JsonWriter writer, long value, JsonSerializerOptions options) =>
        writer.WriteNumberValue(value);
}
