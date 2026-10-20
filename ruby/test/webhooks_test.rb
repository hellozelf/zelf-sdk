require_relative 'helper'
require 'digest'
require 'openssl'

class WebhooksTest < Minitest::Test
  SECRET = 'whsec_abcdef0123456789'.freeze
  EventType = Zelf::Webhooks::EventType

  def snapshot(type: EventType::CONTENT_SNAPSHOT, items: nil, files: nil)
    data = { 'item_count' => items ? items.length : 1 }
    data['items'] = items if items
    data['files'] = files if files
    {
      'id' => 'whd_8f2c1d4e9a',
      'type' => type,
      'subscription_id' => 'whs_5Kq9Wd2pBxLm',
      'delivered_at' => 1_718_000_000,
      'livemode' => true,
      'resource' => 'content',
      'delivery_mode' => files ? 'manifest' : 'inline',
      'data' => data
    }
  end

  # Mirrors the signing scheme the API documents.
  def sign(payload, secret, timestamp)
    digest = OpenSSL::HMAC.hexdigest('SHA256', secret, "#{timestamp}.#{payload}")
    { 'Webhook-Signature' => "t=#{timestamp},v1=#{digest}" }
  end

  def delivery(body, secret = SECRET)
    payload = JSON.generate(body)
    now = Time.now.to_f
    [payload, sign(payload, secret, now.to_i), now]
  end

  def test_parse_returns_a_typed_event
    payload, headers, now = delivery(snapshot(items: [{ 'id' => 'con_1' }]))

    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    assert_equal EventType::CONTENT_SNAPSHOT, event.event_type
    assert_equal 'whd_8f2c1d4e9a', event.id
    assert_equal 'whs_5Kq9Wd2pBxLm', event.subscription_id
    assert event.livemode
    assert_equal 2024, event.delivered_at.year
    assert_equal [{ 'id' => 'con_1' }], event.items
    assert_empty event.files
  end

  def test_the_raw_payload_survives_a_field_the_sdk_does_not_know
    payload, headers, now = delivery(snapshot(items: []).merge('future' => 42))

    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    assert_equal 42, event.raw['future']
  end

  def test_an_unrecognised_wire_type_leaves_event_type_nil
    payload, headers, now = delivery(snapshot(type: 'content.from_the_future', items: []))

    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    assert_equal 'content.from_the_future', event.type
    assert_nil event.event_type
  end

  def test_the_event_type_module_covers_every_declared_event
    assert_equal %w[ai_analysis.completed content.snapshot creator.snapshot
                    creator_vetting.completed].sort,
                 EventType::ALL.sort
    assert EventType.known?('content.snapshot')
    refute EventType.known?('content.exploded')
  end

  def test_a_forged_signature_is_rejected
    payload, headers, now = delivery(snapshot(items: []), 'whsec_wrong')

    assert_raises(Zelf::Webhooks::VerificationError) do
      Zelf::Webhooks.parse(payload, headers, SECRET, now: now)
    end
  end

  def test_a_tampered_body_is_rejected
    payload, headers, now = delivery(snapshot(items: []))

    assert_raises(Zelf::Webhooks::VerificationError) do
      Zelf::Webhooks.parse("#{payload} ", headers, SECRET, now: now)
    end
  end

  def test_an_old_delivery_is_rejected_as_a_replay
    payload = JSON.generate(snapshot(items: []))
    stale = Time.now.to_i - 4000

    assert_raises(Zelf::Webhooks::VerificationError) do
      Zelf::Webhooks.parse(payload, sign(payload, SECRET, stale), SECRET)
    end
  end

  def test_a_future_timestamp_is_also_rejected
    payload = JSON.generate(snapshot(items: []))
    ahead = Time.now.to_i + 4000

    assert_raises(Zelf::Webhooks::VerificationError) do
      Zelf::Webhooks.parse(payload, sign(payload, SECRET, ahead), SECRET)
    end
  end

  def test_either_secret_verifies_during_a_rotation
    payload, headers, now = delivery(snapshot(items: []), 'whsec_new')

    assert Zelf::Webhooks.parse(payload, headers, %w[whsec_old whsec_new], now: now)
  end

  def test_a_malformed_signature_header_is_rejected
    payload = JSON.generate(snapshot(items: []))

    ['', 'garbage', 't=abc,v1=ff', 'v1=ff', 't=1718000000'].each do |raw|
      assert_raises(Zelf::Webhooks::VerificationError) do
        Zelf::Webhooks.parse(payload, { 'Webhook-Signature' => raw }, SECRET)
      end
    end
  end

  def test_no_secret_is_a_configuration_error
    payload, headers, now = delivery(snapshot(items: []))

    assert_raises(ArgumentError) do
      Zelf::Webhooks.parse(payload, headers, [], now: now)
    end
  end

  def test_the_handler_routes_to_the_listener_for_the_type
    seen = []
    handler = Zelf::Webhooks::Handler.new(SECRET)
    handler.on(EventType::CONTENT_SNAPSHOT) { |event| seen << "content:#{event.id}"; 'handled' }
    handler.on(EventType::CREATOR_SNAPSHOT) { seen << 'creator' }

    payload, headers, now = delivery(snapshot(items: []))
    results = handler.handle(payload, headers, now: now)

    assert_equal ['content:whd_8f2c1d4e9a'], seen
    assert_equal ['handled'], results
  end

  def test_an_unmatched_event_falls_back_or_is_a_no_op
    seen = []
    with_fallback = Zelf::Webhooks::Handler.new(SECRET)
    with_fallback.on_any { |event| seen << event.type }

    payload, headers, now = delivery(snapshot(type: EventType::AI_ANALYSIS_COMPLETED, items: []))
    with_fallback.handle(payload, headers, now: now)

    assert_equal ['ai_analysis.completed'], seen
    assert_empty Zelf::Webhooks::Handler.new(SECRET).handle(payload, headers, now: now)
  end

  def test_registering_an_unknown_event_type_fails_loudly
    handler = Zelf::Webhooks::Handler.new(SECRET)

    assert_raises(ArgumentError) { handler.on('content.exploded') { nil } }
    assert_raises(ArgumentError) { handler.on { nil } }
  end

  def test_no_listener_runs_when_the_signature_is_bad
    seen = []
    handler = Zelf::Webhooks::Handler.new(SECRET)
    handler.on_any { |event| seen << event.type }

    payload, headers, now = delivery(snapshot(items: []), 'whsec_wrong')

    assert_raises(Zelf::Webhooks::VerificationError) { handler.handle(payload, headers, now: now) }
    assert_empty seen
  end

  NDJSON = "{\"id\":\"con_1\"}\n{\"id\":\"con_2\"}\n".freeze

  def manifest(sha256 = Digest::SHA256.hexdigest(NDJSON))
    snapshot(files: [{ 'format' => 'ndjson', 'expires_at' => 1_718_000_000,
                       'sha256' => sha256, 'size_bytes' => NDJSON.bytesize,
                       'item_count' => 2,
                       'download_url' => 'https://example.invalid/whd_1.ndjson' }])
  end

  def test_rows_downloads_the_manifest_and_yields_each_line
    payload, headers, now = delivery(manifest)
    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    rows = event.rows(http_get: ->(_url) { NDJSON }).to_a

    assert_equal [{ 'id' => 'con_1' }, { 'id' => 'con_2' }], rows
  end

  def test_rows_rejects_a_download_whose_checksum_does_not_match
    payload, headers, now = delivery(manifest)
    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    assert_raises(Zelf::Webhooks::VerificationError) do
      event.rows(http_get: ->(_url) { "{\"id\":\"tampered\"}\n" }).to_a
    end
  end

  def test_rows_rejects_a_manifest_that_published_no_digest
    payload, headers, now = delivery(manifest(''))
    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    error = assert_raises(Zelf::Webhooks::VerificationError) do
      event.rows(http_get: ->(_url) { NDJSON }).to_a
    end
    assert_includes error.message, 'no sha256'
  end

  def test_rows_reads_an_unchecked_file_when_verification_is_waived
    payload, headers, now = delivery(manifest(''))
    event = Zelf::Webhooks.parse(payload, headers, SECRET, now: now)

    rows = event.rows(verify_checksum: false, http_get: ->(_url) { NDJSON }).to_a

    assert_equal [{ 'id' => 'con_1' }, { 'id' => 'con_2' }], rows
  end
end
