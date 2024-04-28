from __future__ import annotations

import logging
from textwrap import dedent

import utils
from models import Company, Contact, Report


def notify(contact: Contact):
    if not contact.confirmed:
        logging.warning(f'Skipping unconfirmed {contact=}')
        return
    reports = Report.select().join(Company).where(
        Report.reported > utils.now(days=-60),
        not contact.notified or Report.reported > contact.notified,
        Company.name.ilike(f'%{contact.company}%'),
        not contact.state or Company.state.like(contact.state))
    notified = utils.now()
    if not reports:
        logging.info(f'No new reports for {contact=}')
        return
    logging.info(f'Notifying {contact=} reports={len(reports)}')
    subject = f'WARN Notice for {contact.company}'
    body = '\n'.join(map(render, reports))
    utils.send_email(contact.email, subject, body)
    contact.notified = notified
    contact.save()

def notify_all():
    for contact in Contact.select().where(Contact.confirmed):
        notify(contact)

def render(report: Report):
    return dedent(f"""
        <h2>{report.company.name}</h2>
        <table>
            <tbody>
                <tr>
                    <th class="row">Company</th>
                    <td>{report.company.name}</td>
                </tr>
                <tr>
                    <th class="row">State</th>
                    <td>{report.company.state}</td>
                </tr>
                <tr>
                    <th class="row">Location</th>
                    <td>{report.location}</td>
                </tr>
                <tr>
                    <th class="row">Employees</th>
                    <td>{report.employees}</td>
                </tr>
                <tr>
                    <th class="row">Reported</th>
                    <td>{report.reported}</td>
                </tr>
                <tr>
                    <th class="row">Starting</th>
                    <td>{report.starting}</td>
                </tr>
            </tbody>
        </table>""")

def main():
    notify_all()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
