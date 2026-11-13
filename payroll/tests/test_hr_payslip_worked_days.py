# Part of Odoo. See LICENSE file for full copyright and licensing details.

import time
from datetime import date, datetime

from odoo.tests import Form

from .common import TestPayslipBase


class TestWorkedDays(TestPayslipBase):
    def setUp(self):
        super().setUp()

        self.LeaveRequest = self.env["hr.leave"]
        self.LeaveType = self.env["hr.work.entry.type"]

        # create holiday type
        self.holiday_type = self.LeaveType.create(
            {
                "name": "TestLeaveType",
                "code": "GLOBAL",
                # count_as defaults to working_time; only absence leaves are
                # deducted from worked days (the batch leave domain filters on it)
                "count_as": "absence",
                "allocation_validation_type": "no_validation",
                "leave_validation_type": "no_validation",
            }
        )

        self.full_calendar = self.ResourceCalendar.create(
            {
                "name": "56 Hrs a week",
            }
        )
        # 20 copies the company default attendances into a new fixed calendar;
        # the test builds its own 7-day schedule from scratch.
        self.full_calendar.attendance_ids.unlink()
        # Create a full 7-day week sor our tests don't fail on Sat. and Sun.
        for day in ["0", "1", "2", "3", "4", "5", "6"]:
            self.CalendarAttendance.create(
                {
                    "calendar_id": self.full_calendar.id,
                    "dayofweek": day,
                    "day_period": "morning",
                    "hour_from": 8,
                    "hour_to": 12,
                }
            )
            self.CalendarAttendance.create(
                {
                    "calendar_id": self.full_calendar.id,
                    "dayofweek": day,
                    "day_period": "afternoon",
                    "hour_from": 13,
                    "hour_to": 17,
                }
            )

    def _common_contract_leave_setup(self):
        self.richard_emp.resource_id.calendar_id = self.full_calendar
        self.richard_emp.version_ids.resource_calendar_id = self.full_calendar

        # I put all eligible contracts (including Richard's) in an "open" state
        self.apply_contract_cron()

        self.env["hr.leave.allocation"].create(
            {
                "name": "Annual Time Off",
                "employee_id": self.richard_emp.id,
                "work_entry_type_id": self.holiday_type.id,
                "number_of_days": 20,
                "state": "confirm",
                "date_from": time.strftime("%Y-01-01"),
                "date_to": time.strftime("%Y-12-31"),
            }
        )

        # Create the leave
        self.LeaveRequest.create(
            {
                "name": "Hol11",
                "employee_id": self.richard_emp.id,
                "work_entry_type_id": self.holiday_type.id,
                "date_from": datetime.combine(date.today(), datetime.min.time()),
                "date_to": datetime.combine(date.today(), datetime.max.time()),
                "number_of_days": 1,
            }
        )

    def test_worked_days_negative(self):
        self._common_contract_leave_setup()

        # Set system parameter
        self.env["ir.config_parameter"].sudo().set_bool(
            "payroll.leaves_positive", False
        )

        # I create an employee Payslip
        frm = Form(self.Payslip)
        frm.employee_id = self.richard_emp
        richard_payslip = frm.save()

        worked_days_codes = richard_payslip.worked_days_line_ids.mapped("code")
        self.assertIn(
            "GLOBAL", worked_days_codes, "The leave is in the 'Worked Days' list"
        )
        wdl_ids = richard_payslip.worked_days_line_ids.filtered(
            lambda x: x.code == "GLOBAL"
        )
        self.assertEqual(len(wdl_ids), 1, "There is only one line matching the leave")
        self.assertEqual(
            wdl_ids[0].number_of_days,
            -1.0,
            "The days worked value is a NEGATIVE number",
        )
        self.assertEqual(
            wdl_ids[0].number_of_hours,
            -8.0,
            "The hours worked value is a NEGATIVE number",
        )

    def test_leaves_positive(self):
        self._common_contract_leave_setup()

        # Set system parameter
        self.env["ir.config_parameter"].sudo().set_bool(
            "payroll.leaves_positive", True
        )

        # I create an employee Payslip
        frm = Form(self.Payslip)
        frm.employee_id = self.richard_emp
        richard_payslip = frm.save()

        worked_days_codes = richard_payslip.worked_days_line_ids.mapped("code")
        self.assertIn(
            "GLOBAL", worked_days_codes, "The leave is in the 'Worked Days' list"
        )
        wdl_ids = richard_payslip.worked_days_line_ids.filtered(
            lambda x: x.code == "GLOBAL"
        )
        self.assertEqual(len(wdl_ids), 1, "There is only one line matching the leave")
        self.assertEqual(
            wdl_ids[0].number_of_days, 1.0, "The days worked value is a POSITIVE number"
        )
        self.assertEqual(
            wdl_ids[0].number_of_hours,
            8.0,
            "The hours worked value is a POSITIVE number",
        )


class TestRetroactiveTimezone(TestPayslipBase):
    """A retroactive payslip must be computed with the contract version's
    timezone, not the employee's current version."""

    def _make_retro_calendar(self):
        calendar = self.ResourceCalendar.create({"name": "Retro 8-20"})
        calendar.attendance_ids.unlink()
        for day in ["0", "1", "2", "3", "4", "5", "6"]:
            self.CalendarAttendance.create(
                {
                    "calendar_id": calendar.id,
                    "dayofweek": day,
                    "day_period": "morning",
                    "hour_from": 8,
                    "hour_to": 20,
                }
            )
        return calendar

    def test_retroactive_leave_uses_contract_timezone(self):
        from datetime import timedelta

        from dateutil.relativedelta import FR, relativedelta

        today = date.today()
        prev_start = today.replace(day=1) - relativedelta(months=1)
        prev_end = today.replace(day=1) - relativedelta(days=1)
        retro_day = prev_start + relativedelta(weekday=FR(+1))
        if retro_day > prev_end:
            retro_day -= relativedelta(weeks=1)

        calendar = self._make_retro_calendar()

        # Contract version for the previous month, UTC timezone, retro calendar
        self.richard_emp.version_id.write(
            {
                "contract_date_start": prev_start.strftime("%Y-%m-%d"),
                "contract_date_end": prev_end.strftime("%Y-%m-%d"),
                "tz": "UTC",
                "resource_calendar_id": calendar.id,
                "struct_id": self.developer_pay_structure.id,
                "wage": 5000.0,
            }
        )
        # Current version, effective from this month, different timezone
        self.Contract.create(
            {
                "name": "Relocation",
                "employee_id": self.richard_emp.id,
                "date_version": today.replace(day=1).strftime("%Y-%m-%d"),
                "contract_date_start": today.replace(day=1).strftime("%Y-%m-%d"),
                "tz": "Asia/Kolkata",
                "struct_id": self.developer_pay_structure.id,
                "wage": 5000.0,
            }
        )

        # Leave 19:00-23:00 UTC on the retro day: it overlaps the retro
        # calendar's attendance (08:00-20:00 UTC) by one hour; interpreted in
        # Asia/Kolkata (the current version's timezone) it falls outside every
        # attendance slot.
        self.env["resource.calendar.leaves"].create(
            {
                "name": "Retro leave",
                "resource_id": self.richard_emp.resource_id.id,
                "calendar_id": calendar.id,
                "date_from": datetime.combine(retro_day, datetime.min.time())
                + timedelta(hours=19),
                "date_to": datetime.combine(retro_day, datetime.min.time())
                + timedelta(hours=23),
                "count_as": "absence",
                "company_id": self.richard_emp.company_id.id,
            }
        )

        res = self.Payslip.get_payslip_vals(prev_start, prev_end, self.richard_emp.id)
        leave_lines = [
            line
            for line in res["value"]["worked_days_line_ids"]
            if line["code"] == "GLOBAL"
        ]
        self.assertEqual(
            len(leave_lines), 1, "The retroactive leave is in the worked days"
        )
        # leaves_positive defaults to False: the leave deducts, sign aside,
        # the absolute hours prove the timezone choice
        self.assertEqual(
            leave_lines[0]["number_of_hours"],
            -1.0,
            "The leave hours are computed in the contract version's timezone",
        )
