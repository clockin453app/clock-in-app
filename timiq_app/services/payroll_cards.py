from html import escape


def build_payroll_employee_card(
    display,
    rows_html,
    wk_hours,
    wk_gross,
    wk_tax,
    wk_net,
    paid,
    paid_at,
    currency,
    money,
):
    return f"""
          <div class="payrollEmployeeCard plainSection" style="padding:12px; margin-top:12px;">
            <div class="payrollEmployeeHead">
              <div class="payrollEmployeeName">{escape(display)}</div>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
              <table class="weeklyEditTable">
                <colgroup>
  <col style="width:38px;">
  <col style="width:78px;">
  <col style="width:56px;">
  <col style="width:56px;">
  <col style="width:46px;">
  <col style="width:64px;">
  <col style="width:64px;">
</colgroup>
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Date</th>
                    <th>Clock In</th>
                    <th>Clock Out</th>
                    <th class="num">Hours</th>
                    <th class="num">Gross</th>
                    <th class="num">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(rows_html)}
                </tbody>
              </table>
            </div>
            <div class="payrollSummaryBar">
    <div class="payrollSummaryItem">
        <div class="k">Hours</div>
        <div class="v">{wk_hours:.2f}</div>
    </div>

    <div class="payrollSummaryItem">
        <div class="k">Gross</div>
        <div class="v">{escape(currency)}{money(wk_gross)}</div>
    </div>

    <div class="payrollSummaryItem">
        <div class="k">Tax</div>
        <div class="v">{escape(currency)}{money(wk_tax)}</div>
    </div>

    <div class="payrollSummaryItem net">
        <div class="k">Net</div>
        <div class="v">{escape(currency)}{money(wk_net)}</div>
    </div>

        <div class="payrollSummaryItem paidat">
        <div class="k">Paid at</div>
        <div class="v">{escape(paid_at) if paid and paid_at else "—"}</div>
    </div>
</div>
          </div>
        """