require_relative 'helper'

class ReportsTest < Minitest::Test
  # Reads every field, nested models and lists included, so a lazy cast that
  # would raise on a malformed value is caught here rather than by a caller.
  def read_all(value)
    case value
    when Zelf::Model
      value.class.public_instance_methods(false).each { |name| read_all(value.public_send(name)) }
    when Array
      value.each { |item| read_all(item) }
    end
  end

  def test_every_malformed_report_case_reads
    FIXTURES['reports'].each do |name, cases|
      cases.each do |kind, document|
        report = Zelf::Models.const_get(name).new(document)
        read_all(report)
        assert_equal document, report.to_h, "#{name}.#{kind}"
      end
    end
  end

  def test_a_decimal_in_a_whole_number_field_is_kept
    document = FIXTURES['reports']['AdvancedAiAnalysisReport']['decimals']
    report = Zelf::Models::AdvancedAiAnalysisReport.new(document)
    assert_equal 12.6, report.summary.videos
    assert_equal 12.6, report.top_creators[0].posts
  end

  def test_missing_and_null_fields_read_as_nil
    report = Zelf::Models::CreatorVettingReport.new('violations' => nil)
    assert_nil report.profile_summary
    assert_nil report.top_themes
    assert_nil report.violations
  end
end
