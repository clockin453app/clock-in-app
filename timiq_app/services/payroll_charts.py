import math
from html import escape


def build_payroll_chart_and_kpis(
    filtered,
    q,
    currency,
    overall_hours,
    overall_gross,
    overall_tax,
    overall_net,
    get_employee_display_name,
    money,
    safe_float,
):
    chart_palette = [
        "#2563eb", "#4482c3", "#16a34a", "#f59e0b", "#ef4444",
        "#06b6d4", "#84cc16", "#ec4899", "#14b8a6", "#5b95cb",
    ]

    chart_totals = {}

    for row in filtered:
        user = (row.get("user") or "").strip()
        if not user:
            continue

        display_name = get_employee_display_name(user)
        if q and q not in user.lower() and q not in display_name.lower():
            continue

        pay_val = safe_float(row.get("pay", "0") or "0", 0.0)
        if pay_val <= 0:
            continue

        chart_totals[user] = round(chart_totals.get(user, 0.0) + pay_val, 2)

    chart_rows = []
    for u, gross_u in chart_totals.items():
        if gross_u <= 0:
            continue
        chart_rows.append({
            "user": u,
            "name": get_employee_display_name(u),
            "gross": round(gross_u, 2),
        })

    chart_rows = sorted(chart_rows, key=lambda x: x["gross"], reverse=True)
    chart_top = chart_rows[:15]
    other_total = round(sum(x["gross"] for x in chart_rows[15:]), 2)

    chart_segments = []
    for i, item in enumerate(chart_top):
        chart_segments.append({
            "label": item["name"],
            "value": item["gross"],
            "color": chart_palette[i % len(chart_palette)],
        })

    if other_total > 0:
        chart_segments.append({
            "label": "Other",
            "value": other_total,
            "color": "#94a3b8",
        })

    total_chart_value = round(sum(x["value"] for x in chart_segments), 2)


    pie_html = "<div class='activityEmpty'>No payroll data for current filters.</div>"

    if total_chart_value > 0:
        angle_acc = 0.0
        stops = []
        label_parts = []

        for seg in chart_segments:
            pct = (seg["value"] / total_chart_value) * 100.0
            start = angle_acc
            end = angle_acc + pct
            mid = (start + end) / 2.0

            stops.append(f"{seg['color']} {start:.2f}% {end:.2f}%")
            angle_acc = end

            theta = math.radians((mid * 3.6) - 90.0)
            x = 50.0 + math.cos(theta) * 28.0
            y = 50.0 + math.sin(theta) * 28.0

            label_parts.append(f'''
                  <div class="payrollPieLabel" style="left:{x:.2f}%; top:{y:.2f}%;">
                    <div class="pct">{pct:.0f}%</div>
                    <div class="amt">{escape(currency)}{money(seg['value'])}</div>
                    <div class="name">{escape(seg['label'])}</div>
                  </div>
                ''')

        pie_html = f'''
              <div class="payrollPieWrap">
                <div class="payrollPie" style="background:conic-gradient({', '.join(stops)});"></div>
                {''.join(label_parts)}
              </div>
            '''

    kpi_strip = f"""
      <div class="kpiStrip">
        <div class="kpiMini"><div class="k">Hours</div><div class="v">{round(overall_hours, 2)}</div></div>
        <div class="kpiMini"><div class="k">Gross</div><div class="v">{escape(currency)}{money(overall_gross)}</div></div>
        <div class="kpiMini"><div class="k">Tax</div><div class="v">{escape(currency)}{money(overall_tax)}</div></div>
        <div class="kpiMini"><div class="k">Net</div><div class="v">{escape(currency)}{money(overall_net)}</div></div>
      </div>
    """

    return pie_html, kpi_strip