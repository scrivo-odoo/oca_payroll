# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from dateutil import relativedelta

from odoo import fields
from odoo.tests import common


class TestPayrollAccount(common.TransactionCase):
    def setUp(self):
        super().setUp()

        # Activate company currency
        self.env.user.company_id.currency_id.active = True

        self.payslip_action_id = self.ref("payroll.hr_payslip_menu")

        # The 18.0 test leaned on demo records (res_partner_12, res_bank_1,
        # res_partner_address_27, hr.dep_rd); the stand runs without demo data,
        # so create the same fixtures here.
        self.res_partner = self.env["res.partner"].create({"name": "John Bank Partner"})
        # 20 dropped res.bank and renamed acc_number to account_number
        self.res_partner_bank = self.env["res.partner.bank"].create(
            {
                "account_number": "001-9876543-21",
                "partner_id": self.res_partner.id,
            }
        )
        self.department = self.env["hr.department"].create(
            {"name": "Research & Development"}
        )
        self.john_address = self.env["res.partner"].create({"name": "John Address"})

        self.hr_employee_john = self.env["hr.employee"].create(
            {
                "address_id": self.john_address.id,
                "birthday": "1984-05-01",
                "children": 0.0,
                "country_id": self.ref("base.in"),
                "department_id": self.department.id,
                "name": "John",
                "bank_account_ids": [(6, 0, [self.res_partner_bank.id])],
            }
        )

        self.account_debit = self.env["account.account"].create(
            {
                "name": "Debit Account",
                "code": "334411",
                "account_type": "expense",
                "reconcile": True,
            }
        )
        self.account_credit = self.env["account.account"].create(
            {
                "name": "Credit Account",
                "code": "114433",
                "account_type": "expense",
                "reconcile": True,
            }
        )

        self.account_journal = self.env["account.journal"].create(
            {
                "name": "Vendor Bills - Test",
                "code": "TEXJ",
                "type": "purchase",
                "default_account_id": self.account_debit.id,
                "refund_sequence": True,
            }
        )

        # The demo salary rules (hr_salary_rule_houserentallowance1, structure_base)
        # are not loaded on a stand without demo data: build the minimal rule set here.
        self.categ_basic = self.env["hr.salary.rule.category"].create(
            {"name": "Basic", "code": "BASIC"}
        )
        self.rule_basic = self.env["hr.salary.rule"].create(
            {
                "name": "Basic",
                "code": "BASIC",
                "category_id": self.categ_basic.id,
                "sequence": 1,
                "amount_select": "code",
                "amount_python_compute": "result = contract.wage",
            }
        )
        self.hr_structure_softwaredeveloper = self.env["hr.payroll.structure"].create(
            {
                "name": "Salary Structure for Software Developer",
                "code": "SD",
                "rule_ids": [(6, 0, self.rule_basic.ids)],
            }
        )

        # 20 has no hr.contract: the contract lives on the employee's version
        self.hr_contract_john = self.hr_employee_john.version_id
        self.hr_contract_john.write(
            {
                "name": "Contract for John",
                "contract_date_start": fields.Date.today(),
                "contract_date_end": fields.Date.to_string(
                    datetime.now() + timedelta(days=365)
                ),
                "wage": 5000.0,
                "struct_id": self.hr_structure_softwaredeveloper.id,
                "journal_id": self.account_journal.id,
            }
        )

    def _update_account_in_rule(self, debit, credit):
        self.rule_basic.write({"account_debit": debit, "account_credit": credit})

    def _prepare_payslip(self, employee):
        date_from = datetime.now()
        date_to = datetime.now() + relativedelta.relativedelta(
            months=+1, day=1, days=-1
        )
        self.hr_payslip = self.env["hr.payslip"].create(
            {
                "employee_id": self.hr_employee_john.id,
                "contract_id": self.hr_contract_john.id,
                "struct_id": self.hr_structure_softwaredeveloper.id,
            }
        )
        res = self.hr_payslip.get_payslip_vals(date_from, date_to, employee.id)
        vals = {
            "struct_id": res["value"]["struct_id"],
            "contract_id": res["value"]["contract_id"],
            "name": res["value"]["name"],
        }
        vals["worked_days_line_ids"] = [
            (0, 0, i) for i in res["value"]["worked_days_line_ids"]
        ]
        vals["input_line_ids"] = [(0, 0, i) for i in res["value"]["input_line_ids"]]
        vals.update({"contract_id": self.hr_contract_john.id})
        self.hr_payslip.write(vals)
        return self.hr_payslip

    def test_00_hr_payslip(self):
        """checking the process of payslip."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)

        # I assign the amount to Input data.
        payslip_input = self.env["hr.payslip.input"].search(
            [("payslip_id", "=", self.hr_payslip.id)]
        )
        payslip_input.write({"amount": 5.0})

        # I verify the payslip is in draft state.
        self.assertEqual(self.hr_payslip.state, "draft", "State not changed!")

        # I click on "Compute Sheet" button.
        self.hr_payslip.with_context(
            {},
            lang="en_US",
            tz=False,
            active_model="hr.payslip",
            department_id=False,
            active_ids=[self.payslip_action_id],
            section_id=False,
            active_id=self.payslip_action_id,
        ).compute_sheet()

        # I want to check cancel button.
        # So I first cancel the sheet then make it set to draft.
        self.hr_payslip.action_payslip_cancel()
        self.assertEqual(self.hr_payslip.state, "cancel", "Payslip is rejected.")
        self.hr_payslip.action_payslip_draft()

        self.hr_payslip.action_payslip_done()

        # I verify that the Accounting Entries are created.
        self.assertTrue(self.hr_payslip.move_id, "Accounting Entries should be created")

        # I verify that the payslip is in done state.
        self.assertEqual(self.hr_payslip.state, "done", "State not changed!")

    def test_hr_payslip_no_accounts(self):
        self._prepare_payslip(self.hr_employee_john)

        # I click on "Compute Sheet" button.
        self.hr_payslip.with_context(
            {},
            lang="en_US",
            tz=False,
            active_model="hr.payslip",
            department_id=False,
            active_ids=[self.payslip_action_id],
            section_id=False,
            active_id=self.payslip_action_id,
        ).compute_sheet()

        # Confirm Payslip (no account moves)
        self.hr_payslip.action_payslip_done()
        self.assertFalse(self.hr_payslip.move_id, "Accounting Entries has been created")

        # I verify that the payslip is in done state.
        self.assertEqual(self.hr_payslip.state, "done", "State not changed!")

    def test_partner_logic_account_types(self):
        """Test partner logic for different account types."""
        # Employee already has work_contact_id auto-created
        employee_partner = self.hr_employee_john.work_contact_id

        # Create register with different partner
        register_partner = self.env["res.partner"].create({"name": "Tax Authority"})
        register = self.env["hr.contribution.register"].create(
            {"name": "Tax Register", "partner_id": register_partner.id}
        )

        # Create rule and payslip line
        rule = self.rule_basic
        rule.register_id = register
        payslip = self._prepare_payslip(self.hr_employee_john)
        line = self.env["hr.payslip.line"].create(
            {"slip_id": payslip.id, "salary_rule_id": rule.id, "name": "Test"}
        )

        # Test asset_receivable -> employee partner
        self.account_credit.account_type = "asset_receivable"
        rule.account_credit = self.account_credit
        self.assertEqual(line._get_partner_id(True), employee_partner.id)

        # Test liability_current -> employee partner
        self.account_credit.account_type = "liability_current"
        self.assertEqual(line._get_partner_id(True), employee_partner.id)

        # Test liability_payable -> register partner
        self.account_credit.account_type = "liability_payable"
        self.assertEqual(line._get_partner_id(True), register_partner.id)

        # Test other account types -> no partner
        self.account_credit.account_type = "expense"
        self.assertFalse(line._get_partner_id(True))

    def test_partner_fallback_uses_primary_bank(self):
        """Without a work contact the partner comes from the primary salary
        account, not from an arbitrary first account."""
        employee = self.hr_employee_john
        employee.work_contact_id = False

        secondary_partner = self.env["res.partner"].create(
            {"name": "Secondary Bank Partner"}
        )
        primary_partner = self.env["res.partner"].create({"name": "Primary Bank Partner"})
        bank_secondary = self.env["res.partner.bank"].create(
            {"account_number": "GB00SECONDARY01", "partner_id": secondary_partner.id}
        )
        bank_primary = self.env["res.partner.bank"].create(
            {"account_number": "GB00PRIMARY001", "partner_id": primary_partner.id}
        )
        employee.bank_account_ids = [(6, 0, [bank_secondary.id, bank_primary.id])]
        employee.salary_distribution = {
            str(bank_primary.id): {
                "sequence": 0,
                "amount": 100.0,
                "amount_is_percentage": True,
            },
            str(bank_secondary.id): {
                "sequence": 1,
                "amount": 0.0,
                "amount_is_percentage": True,
            },
        }
        employee.invalidate_recordset()

        self.account_credit.account_type = "liability_current"
        self.rule_basic.account_credit = self.account_credit
        payslip = self._prepare_payslip(employee)
        line = self.env["hr.payslip.line"].create(
            {
                "slip_id": payslip.id,
                "salary_rule_id": self.rule_basic.id,
                "name": "Primary bank test",
            }
        )
        self.assertEqual(line._get_partner_id(True), primary_partner.id)
