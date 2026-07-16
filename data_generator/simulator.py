import json, random, time, uuid, os
from datetime import datetime, timedelta, timezone
from azure.eventhub import EventHubProducerClient, EventData

CONN_STR = os.environ["EH_SEND_CONNSTR"]
EVENT_TYPES = ["page_view", "product_view", "add_to_cart", "remove_from_cart", "begin_checkout", "purchase"]
PAGES = ["/home","/search", "product", "/cart", "/checkout"]

def make_event(session_pool):
    """Generate one event with intentional data-quality problems"""
    session_id = random.choice(session_pool)
    event = {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "user_id": f"u_{random.randint(1, 5000)}",
        "event_type": random.choices(EVENT_TYPES, weights=[40,25,15,5,8,7])[0],
        "page": random.choice(PAGES),
        "product_id": f"p_{random.randrange(1, 500)}",
        "price": round(random.uniform(5, 500), 2),
        "event_ts": datetime.now(timezone.utc).isoformat(),
        "device": random.choice(["mobile", "desktop", "tablet"]),
    }
 
    r = random.random()
    if r < 0.03:                        # 3% NULL user_id
        event["user_id"] = None
    elif r < 0.05:                      # 2% duplicate evebt (same event_id resent)
        event["_dup"] = True
    elif r < 0.08:                      # 3% late arriving (ts up to 2h in the past)
        late = datetime.now(timezone.utc) - timedelta(minutes=random.randint(10, 120))
        event["event_ts"] = late.isoformat()
    elif r < 0.10:
        event["campaign_id"] = f"cmp_{random.randint(1,20)}"
    return event

def main(events_per_second = 5, duration_minutes=30):
    producer = EventHubProducerClient.from_connection_string(
        CONN_STR, eventhub_name = 'clickstream'
    )
    sessions = [str(uuid.uuid4()) for _ in range(200)]
    end = time.time() + duration_minutes * 60
    last_event =  None
    with producer:
        while time.time() < end:
            batch = producer.create_batch()
            for _ in range(events_per_second):
                ev = make_event(sessions)
                if ev.pop("_dup", False) and last_event:
                    ev = last_event                     # resent previous event
                last_event =  ev
                batch.add(EventData(json.dumps(ev)))
            producer.send_batch(batch)
            time.sleep(1)
    print("Done.")
if __name__ == "__main__":
    main()