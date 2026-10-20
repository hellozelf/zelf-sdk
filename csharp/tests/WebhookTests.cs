using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Xunit;
using Zelf.Webhooks;

namespace Zelf.Tests;

public class WebhookTests
{
    private const string Secret = "whsec_abcdef0123456789";
    private static readonly string[] Secrets = [Secret];

    private static byte[] Body(string type = "content.snapshot", string data = """{"item_count":0}""") =>
        Encoding.UTF8.GetBytes($$"""
            {"id":"whd_8f2c1d4e9a","type":"{{type}}","subscription_id":"whs_5Kq9Wd2pBxLm",
             "delivered_at":1718000000,"livemode":true,"resource":"content",
             "delivery_mode":"inline","data":{{data}}}
            """);

    /// <summary>Mirrors the signing scheme the API documents.</summary>
    private static string Sign(byte[] payload, string secret, long timestamp)
    {
        var prefix = Encoding.UTF8.GetBytes($"{timestamp}.");
        var signed = prefix.Concat(payload).ToArray();
        var mac = HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), signed);
        return $"t={timestamp},v1={Convert.ToHexString(mac).ToLowerInvariant()}";
    }

    private static WebhookOptions At(long now) => new() { Now = now };

    [Fact]
    public void ParseReturnsATypedEvent()
    {
        var payload = Body(data: """{"item_count":1,"items":[{"id":"con_1"}]}""");
        const long now = 1718000000;

        var @event = Webhook.Parse(payload, Sign(payload, Secret, now), Secrets, At(now));

        Assert.Equal(EventType.ContentSnapshot, @event.Kind);
        Assert.Equal("whd_8f2c1d4e9a", @event.Id);
        Assert.Equal("whs_5Kq9Wd2pBxLm", @event.SubscriptionId);
        Assert.True(@event.Livemode);
        Assert.Equal(2024, @event.DeliveredAt.Year);
        Assert.Single(@event.Items);
        Assert.Empty(@event.Files);
        Assert.Equal("whd_8f2c1d4e9a", @event.Raw.GetProperty("id").GetString());
    }

    [Fact]
    public void AnUnrecognisedWireTypeLeavesTheKindNull()
    {
        var payload = Body("content.from_the_future");
        const long now = 1718000000;

        var @event = Webhook.Parse(payload, Sign(payload, Secret, now), Secrets, At(now));

        Assert.Equal("content.from_the_future", @event.Type);
        Assert.Null(@event.Kind);
    }

    [Fact]
    public void TheEventTypeEnumCoversEveryDeclaredEvent()
    {
        foreach (var wire in new[]
                 {
                     "content.snapshot", "creator.snapshot",
                     "creator_vetting.completed", "ai_analysis.completed",
                 })
        {
            var kind = EventTypes.FromWire(wire);
            Assert.NotNull(kind);
            Assert.Equal(wire, kind!.Value.ToWire());
        }
        Assert.Null(EventTypes.FromWire("content.exploded"));
        Assert.Equal(4, EventTypes.All.Count);
    }

    [Fact]
    public void AForgedSignatureIsRejected()
    {
        var payload = Body();
        const long now = 1718000000;

        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Parse(payload, Sign(payload, "whsec_wrong", now), Secrets, At(now)));
    }

    [Fact]
    public void ATamperedBodyIsRejected()
    {
        var payload = Body();
        const long now = 1718000000;
        var signature = Sign(payload, Secret, now);

        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Parse(payload.Append((byte)' ').ToArray(), signature, Secrets, At(now)));
    }

    [Fact]
    public void AnOldOrFutureDeliveryIsRejectedAsAReplay()
    {
        var payload = Body();
        const long stamped = 1718000000;

        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Parse(payload, Sign(payload, Secret, stamped), Secrets, At(stamped + 4000)));
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Parse(payload, Sign(payload, Secret, stamped), Secrets, At(stamped - 4000)));
    }

    [Fact]
    public void EitherSecretVerifiesDuringARotation()
    {
        var payload = Body();
        const long now = 1718000000;

        var @event = Webhook.Parse(
            payload, Sign(payload, "whsec_new", now), ["whsec_old", "whsec_new"], At(now));

        Assert.Equal("whd_8f2c1d4e9a", @event.Id);
    }

    [Theory]
    [InlineData("")]
    [InlineData("garbage")]
    [InlineData("t=abc,v1=ff")]
    [InlineData("v1=ff")]
    [InlineData("t=1718000000")]
    public void AMalformedSignatureHeaderIsRejected(string signature)
    {
        Assert.Throws<WebhookVerificationException>(
            () => Webhook.Parse(Body(), signature, Secrets, At(1718000000)));
    }

    [Fact]
    public void NoSecretIsAConfigurationError()
    {
        var payload = Body();

        Assert.Throws<ArgumentException>(
            () => Webhook.Parse(payload, Sign(payload, Secret, 1718000000), [], At(1718000000)));
    }

    [Fact]
    public async Task TheHandlerRoutesToTheListenerForTheType()
    {
        var seen = new List<string>();
        const long now = 1718000000;
        var handler = new WebhookHandler(Secrets, At(now))
            .On(e => { seen.Add($"content:{e.Id}"); return Task.CompletedTask; }, EventType.ContentSnapshot)
            .On(_ => { seen.Add("creator"); return Task.CompletedTask; }, EventType.CreatorSnapshot);

        var payload = Body();
        await handler.HandleAsync(payload, Sign(payload, Secret, now));

        Assert.Equal(["content:whd_8f2c1d4e9a"], seen);
    }

    [Fact]
    public async Task AnUnmatchedEventFallsBackOrIsANoOp()
    {
        var seen = new List<string>();
        const long now = 1718000000;
        var payload = Body("ai_analysis.completed");
        var signature = Sign(payload, Secret, now);

        await new WebhookHandler(Secrets, At(now))
            .OnAny(e => { seen.Add(e.Type); return Task.CompletedTask; })
            .HandleAsync(payload, signature);
        await new WebhookHandler(Secrets, At(now)).HandleAsync(payload, signature);

        Assert.Equal(["ai_analysis.completed"], seen);
    }

    [Fact]
    public async Task NoListenerRunsWhenTheSignatureIsBad()
    {
        var seen = new List<string>();
        const long now = 1718000000;
        var handler = new WebhookHandler(Secrets, At(now))
            .OnAny(e => { seen.Add(e.Type); return Task.CompletedTask; });

        var payload = Body();

        await Assert.ThrowsAsync<WebhookVerificationException>(
            () => handler.HandleAsync(payload, Sign(payload, "whsec_wrong", now)));
        Assert.Empty(seen);
    }

    [Fact]
    public void RegisteringNoEventTypeIsRejected()
    {
        var handler = new WebhookHandler(Secrets);

        Assert.Throws<ArgumentException>(() => handler.On(_ => Task.CompletedTask));
    }
}
