# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Date

from .common import TestPayslipBase


class TestPayrollRowsOfOneFirm(TestPayslipBase):
    """A user of two companies who works in one of them reads the payroll rows of that
    company and not the rows of the other one, whichever payroll model is read directly."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.other = self.env["res.company"].create({"name": "Another company"})
        self.user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Payroll manager of two companies",
                    "login": "payroll_two_companies",
                    "company_id": self.company.id,
                    "company_ids": [(6, 0, (self.company | self.other).ids)],
                    "group_ids": [
                        (
                            6,
                            0,
                            (
                                self.env.ref("base.group_user")
                                | self.env.ref("payroll.group_payroll_manager")
                            ).ids,
                        )
                    ],
                }
            )
        )
        self.rows = {}
        for key, company in (("own", self.company), ("foreign", self.other)):
            self._make_rows(key, company)

    def _make_rows(self, key, company):
        employee = (
            self.env["hr.employee"]
            .with_company(company)
            .create({"name": f"Worker {key}", "company_id": company.id})
        )
        employee.version_id.write(
            {
                "contract_date_start": Date.today(),
                "wage": 3000.0,
                "struct_id": self.developer_pay_structure.id,
            }
        )
        if "journal_id" in self.Contract._fields:
            journal = self.env["account.journal"].search(
                [("type", "=", "general"), ("company_id", "=", company.id)], limit=1
            ) or self.env["account.journal"].create(
                {
                    "name": f"Salary {key}",
                    "code": f"S{key[:2].upper()}",
                    "type": "general",
                    "company_id": company.id,
                }
            )
            employee.version_id.write({"journal_id": journal.id})
        slip = (
            self.Payslip.with_company(company)
            .create(
                {
                    "employee_id": employee.id,
                    "contract_id": employee.version_id.id,
                    "struct_id": self.developer_pay_structure.id,
                    "company_id": company.id,
                }
            )
        )
        slip.compute_sheet()
        run = self.env["hr.payslip.run"].create(
            {"name": f"Run {key}", "company_id": company.id}
        )
        days = self.env["hr.payslip.worked_days"].create(
            {
                "payslip_id": slip.id,
                "name": "Normal",
                "code": f"WORK_{key}",
                "number_of_days": 20,
                "number_of_hours": 160,
                "contract_id": employee.version_id.id,
            }
        )
        slip_input = self.env["hr.payslip.input"].create(
            {
                "payslip_id": slip.id,
                "name": f"Input {key}",
                "code": f"IN_{key}",
                "amount": 1.0,
                "contract_id": employee.version_id.id,
            }
        )
        rule = self.SalaryRule.create(
            {
                "name": f"Rule {key}",
                "code": f"RULE_{key}",
                "category_id": self.categ_basic.id,
                "company_id": company.id,
            }
        )
        rule_input = self.RuleInput.create(
            {"name": f"Rule input {key}", "code": f"RI_{key}", "input_id": rule.id}
        )
        self.rows.setdefault("hr.payslip", {})[key] = slip
        self.rows.setdefault("hr.payslip.line", {})[key] = slip.line_ids[:1]
        self.rows.setdefault("hr.payslip.run", {})[key] = run
        self.rows.setdefault("hr.payslip.worked_days", {})[key] = days
        self.rows.setdefault("hr.payslip.input", {})[key] = slip_input
        self.rows.setdefault("hr.rule.input", {})[key] = rule_input

    def test_row_of_own_company_is_read_and_row_of_other_company_is_not(self):
        """Every payroll model: the row of the company the user works in is found, the
        row of the other company, which the user may access, is not."""
        for model, rows in self.rows.items():
            with self.subTest(model=model):
                self.assertTrue(rows["own"] and rows["foreign"], f"no {model} row")
                found = (
                    self.env[model]
                    .with_user(self.user)
                    .with_context(allowed_company_ids=self.company.ids)
                    .search([("id", "in", (rows["own"] | rows["foreign"]).ids)])
                )
                self.assertEqual(found.ids, rows["own"].ids)
