require 'digest'
require 'json'
require 'net/http'
require 'openssl'
require 'uri'

module Zelf
  # Verifies and routes the deliveries ZelfAI posts to a receiver.
  module Webhooks
    SIGNATURE_HEADER = 'Webhook-Signature'.freeze
    TIMESTAMP_HEADER = 'Webhook-Timestamp'.freeze
    ID_HEADER = 'Webhook-Id'.freeze

    # How far a delivery's timestamp may sit from now before it reads as a replay.
    DEFAULT_TOLERANCE_SECONDS = 300

    # Raised for every failed verification. Answer one with a 400 and never
    # process the body.
    class VerificationError < StandardError; end

    module_function

    def header(headers, name)
      wanted = name.downcase
      headers.each do |key, value|
        return Array(value).first if key.to_s.downcase == wanted
      end
      nil
    end

    def parse_signature(raw)
      timestamp = nil
      digests = []
      raw.to_s.split(',').each do |part|
        key, _, value = part.strip.partition('=')
        if key == 't' && timestamp.nil?
          timestamp = Integer(value, exception: false)
          raise VerificationError, 'signature timestamp is not an integer' if timestamp.nil?
        elsif key == 'v1'
          digests << value
        end
      end
      raise VerificationError, 'signature header is missing a t or v1 component' if timestamp.nil? || digests.empty?

      [timestamp, digests]
    end

    # Verify a delivery and return the decoded payload as a plain hash.
    #
    # +payload+ must be the exact bytes received: re-encoding the JSON changes
    # the bytes and the signature will not match.
    #
    # A rotation switches at once: the API signs the next delivery with the new
    # secret only and rejects the old one immediately. An array of secrets is
    # accepted, so both can be held during a rollout.
    #
    # The comparison runs through OpenSSL.secure_compare, which is constant
    # time, so a wrong signature cannot be recovered from response timing.
    def verify(payload, headers, secret, tolerance_seconds: DEFAULT_TOLERANCE_SECONDS, now: nil)
      secrets = Array(secret)
      raise ArgumentError, 'at least one signing secret is required' if secrets.empty?

      raw = header(headers, SIGNATURE_HEADER)
      raise VerificationError, "missing #{SIGNATURE_HEADER} header" if raw.nil? || raw.empty?

      timestamp, digests = parse_signature(raw)

      if tolerance_seconds.positive?
        age = ((now || Time.now.to_f) - timestamp).abs
        if age > tolerance_seconds
          raise VerificationError,
                "timestamp is #{age.round}s away from now, outside the " \
                "#{tolerance_seconds}s tolerance, so this is a replay"
        end
      end

      signed = "#{timestamp}.#{payload}"
      matched = false
      secrets.each do |candidate|
        want = OpenSSL::HMAC.hexdigest('SHA256', candidate, signed)
        digests.each do |got|
          matched = true if secure_compare(want, got)
        end
      end
      raise VerificationError, 'no signature matched the supplied secrets' unless matched

      body = begin
        JSON.parse(payload)
      rescue JSON::ParserError
        raise VerificationError, 'body is not valid JSON'
      end
      raise VerificationError, 'body is not a JSON object' unless body.is_a?(Hash)

      body
    end

    def secure_compare(left, right)
      if OpenSSL.respond_to?(:secure_compare)
        OpenSSL.secure_compare(left, right)
      else
        # Ruby 2.6 has no OpenSSL.secure_compare; compare fixed-width digests
        # byte by byte without an early exit.
        return false unless left.bytesize == right.bytesize

        left.bytes.zip(right.bytes).reduce(0) { |acc, (a, b)| acc | (a ^ b) }.zero?
      end
    end

    # Verify a delivery and return it as a typed Event.
    def parse(payload, headers, secret, tolerance_seconds: DEFAULT_TOLERANCE_SECONDS, now: nil)
      Event.new(verify(payload, headers, secret,
                       tolerance_seconds: tolerance_seconds, now: now))
    end

    # A delivery whose signature has already been checked.
    class Event
      attr_reader :raw

      def initialize(raw)
        @raw = raw
      end

      def id
        @raw['id']
      end

      # The wire value, which may be newer than this SDK's EVENT_TYPES.
      def type
        @raw['type']
      end

      # The declared event type, or nil for one the SDK predates.
      def event_type
        EventType.known?(type) ? type : nil
      end

      def subscription_id
        @raw['subscription_id']
      end

      def livemode
        @raw['livemode'] ? true : false
      end

      def delivered_at
        Time.at(@raw['delivered_at'].to_i).utc
      end

      def delivery_mode
        @raw['delivery_mode']
      end

      def data
        @raw['data'] || {}
      end

      def item_count
        data['item_count'].to_i
      end

      # Downloadable snapshot files. Populated in +manifest+ mode only.
      def files
        Array(data['files'])
      end

      # Rows carried in the body. Populated in +inline+ mode only.
      def items
        Array(data['items'])
      end

      def statistics
        data['statistics']
      end

      def inspect
        "#<Zelf::Webhooks::Event #{type} id=#{id} items=#{item_count}>"
      end

      # Download the manifest files and yield one decoded row per line.
      #
      # Each download_url is signed and expires, so fetch soon after delivery.
      # With +verify_checksum+ the published SHA-256 is recomputed over the
      # body, and a mismatch or a missing digest raises before any row is
      # yielded.
      def rows(verify_checksum: true, http_get: nil)
        return enum_for(:rows, verify_checksum: verify_checksum, http_get: http_get) unless block_given?

        files.each do |handle|
          body = (http_get || method(:fetch)).call(handle['download_url'])
          if verify_checksum
            published = handle['sha256'].to_s
            if published.empty?
              raise VerificationError,
                    "the manifest published no sha256 for #{handle['download_url']}, so the " \
                    'file cannot be verified; pass verify_checksum: false to read it unchecked'
            end
            digest = Digest::SHA256.hexdigest(body)
            unless Webhooks.secure_compare(digest, published)
              raise VerificationError,
                    "downloaded file digest #{digest} does not match the published #{published}"
            end
          end
          body.each_line do |line|
            next if line.strip.empty?

            yield JSON.parse(line)
          end
        end
        nil
      end

      private

      def fetch(url)
        uri = URI.parse(url)
        response = Net::HTTP.get_response(uri)
        unless response.code.to_i < 400
          raise VerificationError, "downloading the snapshot failed with HTTP #{response.code}"
        end

        response.body.to_s
      end
    end

    # Verify a delivery once, then route it to the listener for its type.
    #
    # Framework agnostic: hand it the raw body and the request headers from
    # whatever server is in front of it.
    class Handler
      def initialize(secret, tolerance_seconds: DEFAULT_TOLERANCE_SECONDS)
        @secret = secret
        @tolerance_seconds = tolerance_seconds
        @listeners = {}
        @fallback = nil
      end

      # Register a listener for one or more event types.
      def on(*event_types, &listener)
        raise ArgumentError, 'pass at least one event type to listen for' if event_types.empty?

        unknown = event_types.map(&:to_s).reject { |name| EventType.known?(name) }
        unless unknown.empty?
          raise ArgumentError,
                "unknown event type(s) #{unknown.join(', ')}. " \
                "Known types: #{EventType::ALL.join(', ')}"
        end

        event_types.each { |name| (@listeners[name.to_s] ||= []) << listener }
        self
      end

      # Register the listener used when no type specific one matched.
      def on_any(&listener)
        @fallback = listener
        self
      end

      # Verify, then call every listener registered for the event type. Raises
      # before any listener runs if the delivery does not check out.
      def handle(payload, headers, now: nil)
        event = Webhooks.parse(payload, headers, @secret,
                               tolerance_seconds: @tolerance_seconds, now: now)
        listeners = @listeners[event.type]
        if listeners.nil? || listeners.empty?
          return @fallback ? [@fallback.call(event)] : []
        end

        listeners.map { |listener| listener.call(event) }
      end
    end
  end
end
