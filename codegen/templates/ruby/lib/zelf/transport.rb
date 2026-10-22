require 'json'
require 'net/http'
require 'uri'
require 'time'

module Zelf
  # The production Zelf API.
  DEFAULT_BASE_URL = 'https://api.hellozelf.com'.freeze
  # Read when no key is passed explicitly.
  API_KEY_ENV = 'ZELF_API_KEY'.freeze
  # Read when no base URL is passed explicitly.
  BASE_URL_ENV = 'ZELF_BASE_URL'.freeze

  # Carries out the HTTP work: auth, retries, and envelope decoding.
  class Transport
    RETRY_STATUSES = [429, 500, 502, 503, 504].freeze
    # The API documents no Idempotency-Key header, so a retried write could
    # create a second analysis, vetting, or sync job.
    RETRY_SAFE_METHODS = %w[GET HEAD OPTIONS].freeze
    MAX_BACKOFF = 8.0

    attr_reader :base_url, :max_retries, :retry_writes

    def initialize(api_key: nil, base_url: nil, timeout: 60,
                   max_retries: 2, retry_writes: false, headers: {})
      base_url ||= ENV[BASE_URL_ENV]
      base_url = DEFAULT_BASE_URL if base_url.nil? || base_url.empty?
      key = api_key || ENV[API_KEY_ENV]
      raise ArgumentError, "an API key is required; pass api_key: or set #{API_KEY_ENV}" if key.nil? || key.empty?
      raise ArgumentError, 'max_retries must be zero or greater' if max_retries.negative?

      @api_key = key
      @base_url = base_url.sub(%r{/+\z}, '')
      @timeout = timeout
      @max_retries = max_retries
      @retry_writes = retry_writes
      # A caller's copy of the API key is dropped whatever its casing, so it
      # cannot replace the client's own.
      @headers = headers.reject { |name, _| name.to_s.casecmp?('x-api-key') }
    end

    # The key must never reach a log line.
    def inspect
      "#<Zelf::Transport base_url=#{@base_url.inspect} api_key=\"***\">"
    end

    def resolve_path(path, path_params)
      path_params.each do |name, value|
        if value.nil? || value.to_s.empty?
          raise ArgumentError, "#{name} is required and must not be empty"
        end

        path = path.sub("{#{name}}", URI.encode_www_form_component(value.to_s).gsub('+', '%20'))
      end
      path
    end

    def self.encode_query(query)
      pairs = []
      query.each do |key, value|
        next if value.nil?

        Array(value).each do |item|
          next if item.nil?

          pairs << [key.to_s, stringify(item)]
        end
      end
      pairs
    end

    def self.stringify(value)
      case value
      when true then 'true'
      when false then 'false'
      when Time then value.iso8601
      when Date then value.iso8601
      else value.to_s
      end
    end

    def request(method, path, path_params: {}, query: {}, body: nil)
      resolved = resolve_path(path.dup, path_params)
      pairs = self.class.encode_query(query)
      last = nil

      (0..@max_retries).each do |attempt|
        response = nil
        begin
          response = send_once(method, resolved, pairs, body)
          return decode(response) if response.code.to_i < 400

          last = Errors.from_response(response)
        rescue Timeout::Error, Net::OpenTimeout, Net::ReadTimeout => e
          last = TimeoutError.new(e.message)
        rescue SystemCallError, SocketError, IOError => e
          last = ConnectionError.new(e.message)
        end

        break if attempt == @max_retries || !retry?(method, response)

        sleep(backoff(attempt, response))
      end

      raise(last || ConnectionError.new('the request was never sent'))
    end

    private

    def retry?(method, response)
      return false unless RETRY_SAFE_METHODS.include?(method.to_s.upcase) || @retry_writes
      return true if response.nil?

      RETRY_STATUSES.include?(response.code.to_i)
    end

    def backoff(attempt, response)
      header = response && response['retry-after']
      if header
        seconds = Float(header, exception: false)
        return [seconds, 60.0].min if seconds && seconds >= 0
      end
      base = [MAX_BACKOFF, 0.5 * (2**attempt)].min
      base * (0.5 + (rand / 2))
    end

    def send_once(method, path, pairs, body)
      uri = URI.parse("#{@base_url}#{path}")
      uri.query = URI.encode_www_form(pairs) unless pairs.empty?

      request_class = Net::HTTP.const_get(method.to_s.capitalize)
      request = request_class.new(uri)
      request['accept'] = 'application/json'
      request['user-agent'] = "zelf-ruby/#{Zelf::VERSION}"
      @headers.each { |name, value| request[name.to_s] = value.to_s }
      # Last, so the client's own key always wins.
      request['x-api-key'] = @api_key
      if body
        request['content-type'] = 'application/json'
        request.body = JSON.generate(body)
      end

      Net::HTTP.start(uri.hostname, uri.port,
                      use_ssl: uri.scheme == 'https',
                      open_timeout: @timeout,
                      read_timeout: @timeout) do |http|
        http.request(request)
      end
    end

    def decode(response)
      return {} if response.code.to_i == 204

      raw = response.body.to_s
      return {} if raw.strip.empty?

      parsed = begin
        JSON.parse(raw)
      rescue JSON::ParserError
        raise APIError.new('the API returned a response that is not valid JSON',
                           status: response.code.to_i)
      end
      unless parsed.is_a?(Hash)
        raise APIError.new('the API returned a response envelope that is not an object',
                           status: response.code.to_i)
      end
      parsed
    end
  end
end
