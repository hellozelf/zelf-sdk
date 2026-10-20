$LOAD_PATH.unshift(File.expand_path('lib', __dir__))
require 'zelf'

BRAND = 'brd_6u599tNI2jemKDcb'.freeze
SCOPE = { brand_id: BRAND, posted_within_days: 365, view_count_min: 250_000_000 }.freeze

def check(name)
  started = Time.now
  detail = yield
  status = 'PASS'
rescue StandardError => e
  status = 'FAIL'
  detail = "#{e.class}: #{e.message}"
ensure
  ms = ((Time.now - started) * 1000).round
  puts format('%-34s %s  %6dms  %s', name, status, ms, detail.to_s[0, 90])
end

client = Zelf::Client.new(api_key: ENV.fetch('ZELF_API_KEY'))

check('usage.retrieve') { "usage ok #{client.usage.retrieve.class}" }
check('content.list') do
  page = client.content.list(**SCOPE, page_size: 3)
  "items=#{page.item_count} first=#{page.results[0].id} views=#{page.results[0].view_count}"
end
check('content.list auto_paging max_pages:2') do
  page = client.content.list(**SCOPE, page_size: 3)
  "walked #{page.auto_paging(max_pages: 2).count} across <=2 pages"
end
check('content.details') do
  page = client.content.list(**SCOPE, page_size: 1)
  found = client.content.details(page.results[0].id, brand_id: BRAND)
  "id=#{found.id} platform=#{found.platform}"
end
check('content.details (missing)') do
  client.content.details('con_J64wsBXg9rmhOE6dFX')
  'no error raised'
rescue Zelf::APIError => e
  "APIError status=#{e.status} code=#{e.code}"
end
check('bad key -> 401 typed') do
  bad = Zelf::Client.new(api_key: 'sk_zelf_definitely_invalid', max_retries: 0)
  bad.usage.retrieve
  'no error raised'
rescue Zelf::APIError => e
  "#{e.status} #{e.code}"
end
check('brands.list') { "brands=#{client.brands.list.item_count}" }
check('webhooks.list_events') { "events=#{client.webhooks.list_events.length}" }
check('brand_accounts.list') do
  groups = client.brand_accounts.list(brand_id: BRAND, account_type: 'tracked')
  "groups=#{groups.length} tracked=#{(groups[0].tracked || []).length}"
end
