# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import Form, common


class TestSalaryJournalOnContract(common.TransactionCase):
    """The salary journal and the analytic account of a contract can be set
    where the user works: on the employee form and in a contract template.

    A payslip takes its journal from the contract and cannot be saved without
    it, so a contract whose journal can only be set outside the screens leaves
    the payslip unusable for anybody who works through them.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env["account.journal"].create(
            {"name": "Salaries - Test", "code": "SALT", "type": "general"}
        )
        plan = cls.env["account.analytic.plan"].create({"name": "Payroll - Test"})
        cls.analytic = cls.env["account.analytic.account"].create(
            {"name": "Payroll - Test", "plan_id": plan.id}
        )
        cls.structure = cls.env["hr.payroll.structure"].create(
            {"name": "Structure - Test", "code": "STRT"}
        )
        cls.template = cls.env["hr.version"].create(
            {
                "name": "Template - Test",
                "journal_id": cls.journal.id,
                "analytic_account_id": cls.analytic.id,
                "struct_id": cls.structure.id,
            }
        )
        cls.template_without_journal = cls.env["hr.version"].create(
            {"name": "Template without journal - Test", "struct_id": cls.structure.id}
        )

    def _employee(self, template=None):
        values = {"name": "Employee - Test"}
        if template:
            values["contract_template_id"] = template.id
        return self.env["hr.employee"].create(values)

    def _payslip(self, employee):
        return self.env["hr.payslip"].create(
            {
                "employee_id": employee.id,
                "contract_id": employee.version_id.id,
                "struct_id": self.structure.id,
            }
        )

    def test_a_template_carries_the_journal_and_the_analytic_account(self):
        employee = self._employee(self.template)
        self.assertEqual(employee.version_id.journal_id, self.journal)
        self.assertEqual(employee.version_id.analytic_account_id, self.analytic)

    def test_a_template_without_a_journal_gives_the_contract_none(self):
        employee = self._employee(self.template_without_journal)
        self.assertFalse(employee.version_id.journal_id)
        self.assertFalse(employee.version_id.analytic_account_id)

    def test_the_journal_is_set_on_the_employee_form(self):
        employee = self._employee()
        with Form(employee) as form:
            form.journal_id = self.journal
        self.assertEqual(employee.version_id.journal_id, self.journal)

    def test_the_employee_form_leaves_the_journal_empty_when_nobody_sets_it(self):
        employee = self._employee()
        with Form(employee) as form:
            form.name = "Employee - Test renamed"
        self.assertFalse(employee.version_id.journal_id)

    def test_a_payslip_takes_the_journal_that_came_through_the_template(self):
        payslip = self._payslip(self._employee(self.template))
        self.assertEqual(payslip.journal_id, self.journal)

    def test_a_payslip_of_a_contract_without_a_journal_has_none(self):
        payslip = self._payslip(self._employee(self.template_without_journal))
        self.assertFalse(payslip.journal_id)
