from boostburn.pricing_scraper import parse_pricing_html


def test_parse_pricing_html_basic_table():
    html = """
    <html>
      <body>
        <table>
          <tr>
            <th>Model</th>
            <th>Price per 1,000 input tokens</th>
            <th>Price per 1,000 output tokens</th>
          </tr>
          <tr>
            <td>Claude Sonnet 4.5</td>
            <td>$0.003</td>
            <td>$0.015</td>
          </tr>
        </table>
      </body>
    </html>
    """
    rates, stats = parse_pricing_html(html, region_override="us-east-2")
    assert stats.models_parsed == 1
    assert "claude-sonnet-4-5" in rates
    entry = rates["claude-sonnet-4-5"]["us-east-2"]
    assert entry["input_per_1k"] == 0.003
    assert entry["output_per_1k"] == 0.015


def test_parse_pricing_html_multirow_headers():
    html = """
    <html>
      <body>
        <table>
          <tr>
            <th rowspan="2">Model</th>
            <th colspan="2">On-Demand</th>
            <th colspan="2">Batch</th>
          </tr>
          <tr>
            <th>Input tokens</th>
            <th>Output tokens</th>
            <th>Input tokens</th>
            <th>Output tokens</th>
          </tr>
          <tr>
            <td>Claude 3.5 Sonnet (Public Extended Access, Effective 1 Dec 2025)</td>
            <td>$0.006</td>
            <td>$0.03</td>
            <td>$0.003</td>
            <td>$0.015</td>
          </tr>
        </table>
      </body>
    </html>
    """
    rates, stats = parse_pricing_html(html, region_override="us-east-2")
    assert stats.models_parsed == 1
    assert "claude-3-5-sonnet" in rates
    entry = rates["claude-3-5-sonnet"]["us-east-2"]
    assert entry["input_per_1k"] == 0.006
    assert entry["output_per_1k"] == 0.03


def test_parse_pricing_html_inline_block():
    html = """
    <html>
      <body>
        <div>
          Claude 3 Opus (Public Extended Access, Effective 1 Dec 2025)
          US East (Ohio)
          Input - $15 per 1,000 tokens
          Output - $75 per 1,000 tokens
        </div>
      </body>
    </html>
    """
    rates, stats = parse_pricing_html(html)
    assert stats.inline_rows_parsed == 1
    assert "claude-3-opus" in rates
    entry = rates["claude-3-opus"]["us-east-2"]
    assert entry["input_per_1k"] == 15.0
    assert entry["output_per_1k"] == 75.0
