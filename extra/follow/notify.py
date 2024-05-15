from __future__ import annotations

from wrep import utils
from wrep.models import *

from .models import *

logger = utils.get_logger('notify')
template = 'email/notify.jinja'

def notify(follow: Follow):
    if not follow.confirmed:
        logger.warning(f'Skipping unconfirmed {follow=}')
        return
    notified = utils.now()
    reports = get_reports(follow)
    if not reports:
        logger.info(f'No new reports for {follow=}')
        return
    subject = f'WARN Notice for {follow.company}'
    body = utils.render(template, reports=reports, follow=follow)
    logger.info(f'Notifying {follow=} reports={len(reports)}')
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

class Command(utils.BaseCommand):
    'Send follow notifications'

    def run(self):
        notify_all()

if __name__ == '__main__':
    Command.main()
