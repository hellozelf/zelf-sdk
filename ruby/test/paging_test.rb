require_relative 'helper'

class PagingTest < Minitest::Test
  # Serves `count` pages of one row each.
  def paged(count)
    lambda do |n, _request|
      page = n
      [200, envelope([content_row("con_#{page}")],
                     page: page,
                     next_page: page < count ? page + 1 : nil)]
    end
  end

  def walk(count, **limits)
    with_server(paged(count)) do |client, server|
      page = client.content.list(search: 'x')
      ids = page.auto_paging(**limits).map(&:id)
      [ids, server.requests.length]
    end
  end

  def test_max_pages_stops_the_walk_early
    ids, calls = walk(5, max_pages: 3)

    assert_equal %w[con_1 con_2 con_3], ids
    assert_equal 3, calls
  end

  def test_max_pages_of_one_makes_no_further_request
    ids, calls = walk(5, max_pages: 1)

    assert_equal %w[con_1], ids
    assert_equal 1, calls
  end

  def test_max_items_stops_before_a_page_it_does_not_need
    ids, calls = walk(5, max_items: 2)

    assert_equal %w[con_1 con_2], ids
    assert_equal 2, calls
  end

  def test_no_limit_walks_everything
    ids, calls = walk(4)

    assert_equal %w[con_1 con_2 con_3 con_4], ids
    assert_equal 4, calls
  end

  def test_pages_honours_max_pages
    with_server(paged(5)) do |client, server|
      numbers = client.content.list(search: 'x').pages(max_pages: 2).map(&:page)

      assert_equal [1, 2], numbers
      assert_equal 2, server.requests.length
    end
  end

  def test_a_limit_below_one_is_rejected
    with_server(paged(3)) do |client, _server|
      page = client.content.list(search: 'x')

      assert_raises(ArgumentError) { page.auto_paging(max_pages: 0).to_a }
      assert_raises(ArgumentError) { page.auto_paging(max_items: 0).to_a }
    end
  end

  def test_a_page_is_enumerable
    with_server(->(_n, _r) { [200, envelope([content_row('con_1'), content_row('con_2')])] }) do |client, _s|
      page = client.content.list(search: 'x')

      assert_equal %w[con_1 con_2], page.map(&:id)
      assert_equal 2, page.count
    end
  end
end
