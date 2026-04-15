"""
python manage.py run_event_listener

Runs the contract event listener as a long-lived process.
In production: run as a separate process via supervisord or Docker.

Example supervisord config:
  [program:tiketi_listener]
  command=python manage.py run_event_listener
  directory=/app
  autostart=true
  autorestart=true
  stdout_logfile=/var/log/tiketi/listener.log
"""
import logging
from django.core.management.base import BaseCommand

logger = logging.getLogger("tiketi.contracts.listener")


class Command(BaseCommand):
    help = "Run the Tiketi contract event listener"

    def handle(self, *args, **options):
        self.stdout.write("Starting Tiketi contract event listener...")

        from apps.contracts.event_listener import ContractEventListener
        listener = ContractEventListener()

        try:
            listener.run()
        except KeyboardInterrupt:
            self.stdout.write("\nEvent listener stopped.")
