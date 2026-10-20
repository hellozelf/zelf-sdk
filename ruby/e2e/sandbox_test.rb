require 'minitest/autorun'
require 'zelf'

BASE = ENV.fetch('ZELF_BASE_URL', 'https://sandbox-api.hellozelf.com')
KEY = ENV.fetch('ZELF_API_KEY', 'sk_zelf_sandbox_demo')

class SandboxTest < Minitest::Test
  def client(**extra)
    Zelf::Client.new(api_key: KEY, base_url: BASE, **extra)
  end

  def test_usage_decodes
    refute_nil client.usage.retrieve
  end

  def test_a_page_decodes_every_row
    page = client.content.list(page_size: 2)
    assert_equal 2, page.item_count
    page.results.each { |row| assert row.id.start_with?('con_') }
  end

  def test_auto_paging_stops_at_the_bound
    rows = []
    client.content.list(page_size: 2).auto_paging(max_pages: 2) { |row| rows << row }
    assert_equal 4, rows.length
  end

  def test_a_bad_key_raises_the_typed_error
    bad = Zelf::Client.new(api_key: "sk_zelf_#{'9' * 64}", base_url: BASE, max_retries: 0)
    error = assert_raises(Zelf::AuthenticationError) { bad.usage.retrieve }
    assert_equal 401, error.status
    assert_equal 'INVALID_API_KEY', error.code
  end

  def test_a_rate_limit_is_retried_then_surfaced
    throttled = client(max_retries: 1,
                       headers: { 'x-sandbox-force-error' => 'RATE_LIMIT_EXCEEDED' })
    error = assert_raises(Zelf::RateLimitError) { throttled.usage.retrieve }
    assert_equal 429, error.status
  end

  def test_event_types_are_listed
    refute_empty client.webhooks.list_events
  end
end
