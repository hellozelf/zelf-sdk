# frozen_string_literal: true

# One process for the whole suite. Running a file at a time starts a separate
# coverage run per file, and none of them sees the whole library.
require 'simplecov'

SimpleCov.start do
  enable_coverage :line
  track_files 'lib/**/*.rb'
  add_filter %r{^/test/}
  add_filter %r{^/e2e/}
  add_filter 'live.rb'
  # Ruby and PHP are the two clients with no generated conformance suite, so
  # the resource methods are not driven the way the other six are. This is a
  # regression floor at the level reached today, not the 100% gate the rest of
  # the repo holds; it rises to 100 when emit_conformance gains a Ruby emitter.
  minimum_coverage line: 83
end

Dir[File.expand_path('*_test.rb', __dir__)].sort.each { |file| require file }
