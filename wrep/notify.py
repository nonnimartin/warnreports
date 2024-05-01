from __future__ import annotations

import logging
from argparse import ArgumentParser

from . import utils
from .models import Follow, Report

template = 'email/notify.jinja'

def notify(follow: Follow):
    if not follow.confirmed:
        logging.warning(f'Skipping unconfirmed {follow=}')
        return
    notified = utils.now()
    reports = get_reports(follow)
    if not reports:
        logging.info(f'No new reports for {follow=}')
        return
    subject = f'WARN Notice for {follow.company}'
    body = utils.render(template, reports=reports, follow=follow)
    logging.info(f'Notifying {follow=} reports={len(reports)}')
    if utils.send_email(follow.email, subject, body):
        follow.notified = notified
        follow.save()

def get_reports(follow: Follow):
    reports = Report.select().where(
        Report.reported > utils.now(days=-60),
        not follow.notified or Report.reported > follow.notified,
        Report.company.ilike(f'%{follow.company}%'),
        follow.state == '*' or Report.state.like(follow.state))
    return reports.order_by(Report.reported.desc())

def notify_all():
    for follow in Follow.select().where(Follow.confirmed):
        notify(follow)

def main():
    parser = ArgumentParser()
    opts = parser.parse_args()
    notify_all()

if __name__ == '__main__':
    utils.init_logging()
    main()
