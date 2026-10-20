require_relative 'helper'

class ClientTest < Minitest::Test
  def test_list_returns_a_typed_page
    with_server(->(_n, _r) { [200, envelope([content_row])] }) do |client, server|
      page = client.content.list(search: 'running shoes')

      assert_instance_of Zelf::Page, page
      assert_equal 1, page.size
      assert_equal 'con_1', page.results[0].id
      assert_equal 184_230, page.results[0].view_count
      assert_equal 'log_1', page.log_id
      refute page.next?
      assert_includes server.requests[0].query, 'search=running+shoes'
    end
  end

  def test_a_model_field_is_coerced_and_the_raw_hash_survives
    with_server(->(_n, _r) { [200, envelope([content_row])] }) do |client, _server|
      item = client.content.list(search: 'x').results[0]

      assert_kind_of Time, item.posted_at
      assert_equal 'instagram', item.platform
      assert_equal 'con_1', item.to_h['id']
      assert_kind_of Zelf::Models::ContentCreator, item.creator
    end
  end

  def test_the_api_key_travels_in_a_header_never_the_url
    with_server(->(_n, _r) { [200, envelope([{ 'plan' => 'pro' }])] }) do |client, server|
      client.usage.retrieve

      request = server.requests[0]
      assert_equal API_KEY, request.headers['x-api-key']
      refute_includes request.path.to_s, API_KEY
      refute_includes request.query.to_s, API_KEY
      assert request.headers['user-agent'].start_with?('zelf-ruby/')
    end
  end

  def test_the_api_key_stays_out_of_inspect
    client = Zelf::Client.new(api_key: API_KEY)

    refute_includes client.inspect, API_KEY
    assert_includes client.inspect, '***'
  end

  def test_a_missing_key_fails_before_any_request
    ENV.delete('ZELF_API_KEY')
    assert_raises(ArgumentError) { Zelf::Client.new }
  end

  def test_the_key_falls_back_to_the_environment
    ENV['ZELF_API_KEY'] = 'sk_from_env'
    Zelf::Client.new
  ensure
    ENV.delete('ZELF_API_KEY')
  end

  def test_a_single_read_unwraps_the_envelope
    with_server(->(_n, _r) { [200, envelope([content_row])] }) do |client, _server|
      found = client.content.details('con_1')

      assert_instance_of Zelf::Models::Content, found
      assert_equal 'con_1', found.id
    end
  end

  def test_a_caller_header_cannot_replace_or_duplicate_the_api_key
    server = StubServer.new { |_n, _r| [200, envelope([{ 'plan' => 'pro' }])] }
    client = Zelf::Client.new(api_key: API_KEY, base_url: server.base_url, max_retries: 0,
                              headers: { 'X-API-Key' => 'sk_zelf_a_different_key' })
    client.usage.retrieve

    assert_equal API_KEY, server.requests[0].headers['x-api-key']
  ensure
    server&.close
  end

  def test_a_single_read_that_matches_nothing_raises_not_found
    with_server(->(_n, _r) { [200, envelope([])] }) do |client, _server|
      error = assert_raises(Zelf::NotFoundError) { client.content.details('con_missing') }

      assert_equal 404, error.status
      assert_includes error.message, 'No Content matched the request.'
    end
  end

  def test_path_parameters_are_escaped
    with_server(->(_n, _r) { [200, envelope([content_row])] }) do |client, server|
      client.content.details('con/../../admin')

      assert_includes server.requests[0].path, 'con%2F..%2F..%2Fadmin'
      refute_includes server.requests[0].path, '/../'
    end
  end

  def test_an_empty_path_parameter_is_rejected
    client = Zelf::Client.new(api_key: API_KEY)
    assert_raises(ArgumentError) { client.content.details('') }
  end

  def test_errors_map_to_typed_classes
    body = { 'log_id' => 'log_1',
             'error' => { 'code' => 'INVALID_API_KEY', 'message' => 'Nope.', 'details' => {} } }
    with_server(->(_n, _r) { [401, body] }) do |client, _server|
      error = assert_raises(Zelf::AuthenticationError) { client.content.list(search: 'x') }

      assert_equal 401, error.status
      assert_equal 'INVALID_API_KEY', error.code
      assert_equal 'log_1', error.log_id
      assert_kind_of Zelf::APIError, error
    end
  end

  def test_a_rate_limited_read_is_retried
    responder = lambda do |n, _r|
      n == 1 ? [429, { 'error' => { 'code' => 'RATE_LIMIT_EXCEEDED' } }] : [200, envelope([content_row])]
    end
    server = StubServer.new(&responder)
    client = Zelf::Client.new(api_key: API_KEY, base_url: server.base_url, max_retries: 2)

    page = client.content.list(search: 'x')

    assert_equal 1, page.size
    assert_equal 2, server.requests.length
  ensure
    server&.close
  end

  def test_a_write_is_not_retried_by_default
    server = StubServer.new { [503, { 'error' => { 'code' => 'SERVICE_UNAVAILABLE' } }] }
    client = Zelf::Client.new(api_key: API_KEY, base_url: server.base_url, max_retries: 3)

    assert_raises(Zelf::ServiceUnavailableError) do
      client.creator_sync.create(profile_url: 'https://www.tiktok.com/@zelf')
    end
    # The API has no idempotency key, so a retried create could run twice.
    assert_equal 1, server.requests.length
  ensure
    server&.close
  end

  def test_a_client_error_is_never_retried
    server = StubServer.new { [400, { 'error' => { 'code' => 'VALIDATION_ERROR' } }] }
    client = Zelf::Client.new(api_key: API_KEY, base_url: server.base_url, max_retries: 3)

    assert_raises(Zelf::BadRequestError) { client.content.list(search: 'x') }
    assert_equal 1, server.requests.length
  ensure
    server&.close
  end

  def test_request_bodies_are_sent_as_json
    with_server(->(_n, _r) { [201, envelope([{ 'id' => 'ana_1' }])] }) do |client, server|
      client.ai_analysis.create(name: 'Launch', topic: 'sentiment',
                                content_filters: { 'search' => 'zelf' })

      sent = JSON.parse(server.requests[0].body)
      assert_equal({ 'name' => 'Launch', 'topic' => 'sentiment',
                     'content_filters' => { 'search' => 'zelf' } }, sent)
    end
  end

  def test_array_query_parameters_repeat_the_key
    with_server(->(_n, _r) { [200, envelope([])] }) do |client, server|
      client.content.list(platform: %w[instagram tiktok], is_owned: true)

      query = server.requests[0].query
      assert_includes query, 'platform=instagram'
      assert_includes query, 'platform=tiktok'
      assert_includes query, 'is_owned=true'
      refute_includes query, 'brand_id'
    end
  end
end
