require 'time'

module Zelf
  # Base for every generated response object.
  #
  # The raw hash is kept as it arrived, so a field the API adds before this SDK
  # knows about it is still reachable through +[]+ and +to_h+.
  class Model
    attr_reader :raw

    def initialize(raw)
      @raw = raw.is_a?(Hash) ? raw : {}
    end

    def [](key)
      @raw[key.to_s]
    end

    def to_h
      @raw
    end

    def ==(other)
      other.is_a?(self.class) && other.raw == @raw
    end

    def inspect
      "#<#{self.class.name} #{@raw.inspect}>"
    end

    class << self
      # Declare a field backed by the raw hash.
      #
      # +cast+ names how to coerce the wire value: :time, a model class, or
      # [:list, thing] for an array of them.
      def field(name, wire = nil, cast: nil)
        key = (wire || name).to_s
        define_method(name) { Model.coerce(@raw[key], cast) }
      end

      def coerce(value, cast)
        Model.coerce(value, cast)
      end
    end

    def self.coerce(value, cast)
      return nil if value.nil?

      case cast
      when nil then value
      when :time then (Time.iso8601(value.to_s) rescue value)
      when Array then Array(value).map { |item| coerce(item, cast.first) }
      else cast.new(value)
      end
    end
  end
end
