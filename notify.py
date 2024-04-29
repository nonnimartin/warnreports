from __future__ import annotations

import logging

import utils
from models import Company, Contact, Report


def notify_all():
    for contact in Contact.select().where(Contact.confirmed):
        notify(contact)

def get_reports(contact: Contact):
    reports = Report.select().join(Company).where(
        Report.reported > utils.now(days=-60),
        not contact.notified or Report.reported > contact.notified,
        Company.name.ilike(f'%{contact.company}%'),
        not contact.state or Company.state.like(contact.state))
    return reports.order_by(Report.reported.desc())

def notify(contact: Contact):
    if not contact.confirmed:
        logging.warning(f'Skipping unconfirmed {contact=}')
        return
    reports = get_reports(contact)
    if not reports:
        logging.info(f'No new reports for {contact=}')
        return
    logging.info(f'Notifying {contact=} reports={len(reports)}')
    template = 'notify.jinja'
    context = dict(reports=reports, contact=contact)
    notified = utils.now()
    success = utils.send_email(
        recipient=contact.email,
        subject=f'WARN Notice for {contact.company}',
        body=utils.render(template, context))
    if success:
        contact.notified = notified
        contact.save()

def main():
    notify_all()

if __name__ == '__main__':
    utils.init_logging()
    main()
