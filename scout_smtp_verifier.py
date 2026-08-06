import smtplib
import socket
import logging
from typing import Tuple

try:
    import dns.resolver
except ImportError:
    dns = None

logger = logging.getLogger(__name__)

def verify_email_via_scout_smtp(email: str, timeout: float = 5.0) -> Tuple[bool, str]:
    if not email or "@" not in email:
        return False, "invalid_format"
        
    domain = email.split("@")[-1].strip().lower()
    
    if not dns:
        return False, "dnspython_missing"
        
    try:
        mx_records = dns.resolver.resolve(domain, 'MX', lifetime=timeout)
        mx_host = str(mx_records[0].exchange).rstrip('.')
    except Exception as e:
        logger.debug(f"MX lookup failed for {domain}: {e}")
        return False, f"mx_lookup_failed: {e}"

    try:
        server = smtplib.SMTP(timeout=timeout)
        server.connect(mx_host, 25)
        server.helo(socket.gethostname())
        server.mail('verify@checker-domain.org')
        code, message = server.rcpt(email)
        server.quit()

        if code == 250:
            return True, "valid_deliverable"
        elif code == 550:
            return False, "user_does_not_exist"
        else:
            return False, f"smtp_code_{code}"
    except Exception as e:
        logger.debug(f"SMTP handshake failed for {email}: {e}")
        return False, f"smtp_connect_failed: {e}"