
import requests
import time
import random

def robust_http_waiter_factory(
    *, 
    latest_event_url_template: str,   # e.g. http://eda:8001/orders/{order_id}/events/latest
    status_url_template: str = None,  # e.g. http://eda:8001/orders/{order_id}/status
    expect_event_name: str = "order.final",
    event_field: str = "event",
    status_field: str = "status",
    done_status_values = ("final","completed","done"),
    initial_delay: float = 0.35,      # give the write model a moment to materialize
    backoff_base: float = 0.5,        # starting backoff (s)
    backoff_max: float = 4.0,         # max backoff (s)
    timeout: float = 120.0,
    treat_404_as_not_ready: bool = True,
    treat_204_as_not_ready: bool = True,
):
    """
    A robust waiter that reduces 404 spam and load on your EDA service.
    Strategy:
      1) initial_delay before the first poll (helps when POST returns before projections persist).
      2) Optional 'status' check: if status endpoint returns a non-terminal status (e.g., 200 {'status':'pending'}),
         keep waiting without touching the events endpoint.
      3) Exponential backoff with jitter between polls.
      4) Tolerant of 404/204 as 'not ready' (configurable).
    """
    done_statuses = {s.lower() for s in done_status_values}

    def waiter(order_id: str, hard_timeout: float = None) -> bool:
        if not order_id:
            return False

        if hard_timeout is None:
            hard_timeout = timeout
        deadline = time.time() + hard_timeout

        # small warmup so we don't hammer the read model while it's still catching up
        if initial_delay > 0:
            time.sleep(initial_delay)

        attempt = 0
        backoff = backoff_base

        while time.time() < deadline:
            # 1) If we have a status endpoint, prefer it
            if status_url_template:
                try:
                    surl = status_url_template.format(order_id=order_id)
                    rs = requests.get(surl, timeout=5)
                    if rs.status_code == 200:
                        data = rs.json() if rs.headers.get("content-type","").startswith("application/json") else {}
                        st = str(data.get(status_field, "")).lower()
                        evt = data.get(event_field)
                        # If server exposes event on this endpoint
                        if evt == expect_event_name:
                            return True
                        # Terminal status shortcut
                        if st in done_statuses:
                            return True
                        # Otherwise it's pending/in-progress — skip hitting the events endpoint this round
                    elif rs.status_code in (404, 204):
                        # not ready yet
                        pass
                except Exception:
                    pass

            # 2) Check latest event endpoint
            try:
                eurl = latest_event_url_template.format(order_id=order_id)
                re = requests.get(eurl, timeout=5)
                if re.status_code == 200:
                    data = re.json() if re.headers.get("content-type","").startswith("application/json") else {}
                    if data.get(event_field) == expect_event_name:
                        return True
                elif re.status_code == 204 and treat_204_as_not_ready:
                    pass  # not ready
                elif re.status_code == 404 and treat_404_as_not_ready:
                    pass  # not materialized yet
                else:
                    # Other codes: treat as transient
                    pass
            except Exception:
                # network hiccup etc.
                pass

            # 3) Backoff with jitter
            attempt += 1
            sleep_for = min(backoff, backoff_max) * (0.75 + random.random()*0.5)
            time.sleep(sleep_for)
            backoff = min(backoff_max, backoff * 1.5)

        return False

    return waiter
