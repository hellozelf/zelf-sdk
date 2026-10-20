module Zelf
  # One page of results, plus the envelope metadata that came with it.
  #
  # The page keeps the request that produced it, so the next page is fetched by
  # re-issuing that request with a new +page+ value.
  class Page
    include Enumerable

    attr_reader :results, :log_id, :page, :item_count, :next_page_number,
                :previous_page_number, :applied_filters

    def initialize(envelope, model, transport, path, query)
      @results = Array(envelope['results']).map { |row| model ? model.new(row) : row }
      @log_id = envelope['log_id']
      @page = envelope['page']
      @item_count = envelope['item_count']
      @next_page_number = envelope['next']
      @previous_page_number = envelope['previous']
      @applied_filters = envelope['applied_filters'] || {}
      @model = model
      @transport = transport
      @path = path
      @query = query
    end

    def each(&block)
      @results.each(&block)
    end

    def size
      @results.size
    end

    def next?
      !@next_page_number.nil?
    end

    def inspect
      "#<Zelf::Page page=#{@page} item_count=#{@item_count} next=#{next?}>"
    end

    # The page after this one, or nil when there is none.
    def next_page
      return nil unless next?

      query = @query.reject { |key, _| key.to_s == 'page' }.merge('page' => @next_page_number)
      envelope = @transport.request(:get, @path, query: query)
      Page.new(envelope, @model, @transport, @path, query)
    end

    # Yield this page and the ones after it.
    #
    # +max_pages+ counts this page as the first, so <tt>max_pages: 1</tt>
    # yields only what has already been fetched and makes no further request.
    def pages(max_pages: nil)
      return enum_for(:pages, max_pages: max_pages) unless block_given?

      check_limit!(max_pages, 'max_pages')
      current = self
      seen = 0
      while current
        yield current
        seen += 1
        break if max_pages && seen >= max_pages

        current = current.next_page
      end
    end

    # Walk the remaining pages, yielding one item at a time.
    #
    # +max_pages+ bounds how many pages are fetched and +max_items+ how many
    # items come back. Either one stops the walk, so no page is requested once
    # enough items are in hand.
    def auto_paging(max_pages: nil, max_items: nil)
      return enum_for(:auto_paging, max_pages: max_pages, max_items: max_items) unless block_given?

      check_limit!(max_items, 'max_items')
      produced = 0
      pages(max_pages: max_pages) do |page|
        page.results.each do |row|
          yield row
          produced += 1
          return nil if max_items && produced >= max_items
        end
      end
      nil
    end

    private

    def check_limit!(value, name)
      return if value.nil?
      raise ArgumentError, "#{name} must be 1 or greater" if value < 1
    end
  end

  # Take the single row out of the envelope.
  #
  # Reads that match nothing come back as 200 with an empty +results+ array
  # rather than a 404, so the empty case is raised as a not-found error.
  def self.one(envelope, model, what)
    rows = Array(envelope['results'])
    if rows.empty?
      raise NotFoundError.new("No #{what} matched the request.",
                              status: 404, code: 'NOT_FOUND', log_id: envelope['log_id'])
    end
    model ? model.new(rows.first) : rows.first
  end

  def self.rows(envelope, model)
    Array(envelope['results']).map { |row| model ? model.new(row) : row }
  end
end
