require 'json'
require 'minitest/autorun'
require 'socket'

$LOAD_PATH.unshift(File.expand_path('../lib', __dir__))
require 'zelf'

FIXTURES = JSON.parse(File.read(File.expand_path('../../fixtures/fixtures.json', __dir__)))

API_KEY = 'sk_test_not_a_real_key'.freeze

def content_row(id = 'con_1')
  FIXTURES['envelopes']['content_list']['results'][0].merge('id' => id)
end

def envelope(results, page: 1, next_page: nil)
  {
    'log_id' => 'log_1',
    'timestamp' => '2026-01-01T00:00:00Z',
    'applied_filters' => { 'page' => page },
    'results' => results,
    'item_count' => results.length,
    'page' => page,
    'next' => next_page,
    'previous' => page > 1 ? page - 1 : nil
  }
end

# A minimal HTTP server built on TCPServer, so the suite needs no gems and
# runs on the system Ruby.
class StubServer
  Request = Struct.new(:method, :path, :query, :headers, :body)

  attr_reader :requests

  def initialize(&responder)
    @responder = responder
    @requests = []
    @server = TCPServer.new('127.0.0.1', 0)
    @thread = Thread.new { serve }
  end

  def base_url
    "http://127.0.0.1:#{@server.addr[1]}"
  end

  def close
    @stopping = true
    @server.close
    @thread.kill
  end

  private

  def serve
    loop do
      socket = @server.accept
      handle(socket)
    rescue IOError, Errno::EBADF
      break
    end
  end

  def handle(socket)
    line = socket.gets
    return socket.close if line.nil?

    method, target, = line.split
    headers = {}
    while (header = socket.gets) && header.strip != ''
      name, _, value = header.partition(':')
      headers[name.downcase] = value.strip
    end
    body = nil
    if headers['content-length']
      body = socket.read(headers['content-length'].to_i)
    end

    path, _, query = target.partition('?')
    @requests << Request.new(method, path, query, headers, body)

    status, payload = @responder.call(@requests.length, @requests.last)
    rendered = payload.is_a?(String) ? payload : JSON.generate(payload)
    socket.print("HTTP/1.1 #{status}\r\n")
    socket.print("Content-Type: application/json\r\n")
    socket.print("Content-Length: #{rendered.bytesize}\r\n")
    socket.print("Connection: close\r\n\r\n")
    socket.print(rendered)
    socket.close
  end
end

# Run a block against a stub server. The responder is positional so the block
# stays free for the test body.
def with_server(responder, max_retries: 0)
  server = StubServer.new(&responder)
  client = Zelf::Client.new(api_key: API_KEY, base_url: server.base_url, max_retries: max_retries)
  yield(client, server)
ensure
  server&.close
end
