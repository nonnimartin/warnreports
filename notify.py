from __future__ import annotations

import logging
from argparse import ArgumentParser

import utils
from models import Follow, Report


def notify(follow: Follow):
    if not follow.confirmed:
        logging.warning(f'Skipping unconfirmed {follow=}')
        return
    reports = get_reports(follow)
    if not reports:
        logging.info(f'No new reports for {follow=}')
        return
    logging.info(f'Notifying {follow=} reports={len(reports)}')
    context = dict(reports=reports, follow=follow)
    notified = utils.now()
    success = utils.send_email(
        recipient=follow.email,
        subject=f'WARN Notice for {follow.company}',
        body=utils.render('email/notify.jinja', context))
    if success:
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
