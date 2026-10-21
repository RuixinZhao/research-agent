"""Reference implementation for D-05: Discrete-event simulation for weighted fair scheduling."""
from typing import Any, Dict, List, Optional


def simulate_scheduling(
    jobs: List[Dict[str, Any]],
    flow_weights: Dict[str, float],
    servers: int,
    setup_ms: float,
    horizon_ms: float,
    policy: str,
) -> Dict[str, Any]:
    unarrived = sorted(jobs, key=lambda j: (j["arrival_ms"], j["id"]))
    wait_queue: List[Dict[str, Any]] = []

    server_busy_until = [0.0] * servers
    server_last_flow: List[Optional[str]] = [None] * servers

    allocated_service: Dict[str, float] = {f: 0.0 for f in flow_weights}
    for j in jobs:
        if j["flow"] not in allocated_service:
            allocated_service[j["flow"]] = 0.0

    trace: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []

    now = 0.0

    while True:
        if now >= horizon_ms:
            for j in wait_queue:
                dropped.append({"id": j["id"], "reason": "horizon"})
            wait_queue.clear()
            for j in unarrived:
                dropped.append({"id": j["id"], "reason": "horizon"})
            unarrived.clear()
            break

        # 1. 释放已完成服务端 (busy_until <= now 的服务端变为空闲)
        # server_busy_until[s] <= now 表示当前为空闲

        # 2. 纳入所有 arrival <= now 的任务
        while unarrived and unarrived[0]["arrival_ms"] <= now:
            wait_queue.append(unarrived.pop(0))

        # 3. 丢弃 deadline <= now 的等待任务
        active_wait_queue = []
        for j in wait_queue:
            if j["deadline_ms"] <= now:
                dropped.append({"id": j["id"], "reason": "deadline"})
            else:
                active_wait_queue.append(j)
        wait_queue = active_wait_queue

        # 4. 空闲服务端按编号升序派发
        for s in range(servers):
            if server_busy_until[s] <= now:
                while server_busy_until[s] <= now and wait_queue:
                    if policy == "fifo":
                        best_idx = 0
                        best_key = (wait_queue[0]["arrival_ms"], wait_queue[0]["id"])
                        for idx in range(1, len(wait_queue)):
                            k = (wait_queue[idx]["arrival_ms"], wait_queue[idx]["id"])
                            if k < best_key:
                                best_key = k
                                best_idx = idx
                    elif policy == "fair":
                        best_idx = 0
                        w0 = flow_weights.get(wait_queue[0]["flow"], 1.0)
                        best_key = (
                            allocated_service.get(wait_queue[0]["flow"], 0.0) / w0,
                            wait_queue[0]["arrival_ms"],
                            wait_queue[0]["id"],
                        )
                        for idx in range(1, len(wait_queue)):
                            w = flow_weights.get(wait_queue[idx]["flow"], 1.0)
                            k = (
                                allocated_service.get(wait_queue[idx]["flow"], 0.0) / w,
                                wait_queue[idx]["arrival_ms"],
                                wait_queue[idx]["id"],
                            )
                            if k < best_key:
                                best_key = k
                                best_idx = idx
                    else:
                        raise ValueError(f"Unknown scheduling policy: {policy}")

                    candidate = wait_queue.pop(best_idx)

                    dispatch_ms = now
                    if server_last_flow[s] is None or server_last_flow[s] == candidate["flow"]:
                        setup = 0.0
                    else:
                        setup = float(setup_ms)

                    start_ms = dispatch_ms + setup
                    end_ms = start_ms + candidate["service_ms"]
                    wait_ms = start_ms - candidate["arrival_ms"]

                    if start_ms >= candidate["deadline_ms"]:
                        dropped.append({"id": candidate["id"], "reason": "deadline"})
                        continue
                    elif end_ms > horizon_ms:
                        dropped.append({"id": candidate["id"], "reason": "horizon"})
                        continue
                    else:
                        server_busy_until[s] = end_ms
                        server_last_flow[s] = candidate["flow"]
                        allocated_service[candidate["flow"]] = (
                            allocated_service.get(candidate["flow"], 0.0) + candidate["service_ms"]
                        )

                        entry = dict(candidate)
                        entry.update({
                            "server": s,
                            "dispatch_ms": dispatch_ms,
                            "setup_ms": setup,
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "wait_ms": wait_ms,
                        })
                        trace.append(entry)
                        break

        # 5. 推进时间到下一个到达或完成事件
        future_times = []
        for s in range(servers):
            if server_busy_until[s] > now:
                future_times.append(server_busy_until[s])
        if unarrived:
            future_times.append(unarrived[0]["arrival_ms"])

        if not future_times:
            if wait_queue:
                for j in wait_queue:
                    dropped.append({"id": j["id"], "reason": "horizon"})
                wait_queue.clear()
            break

        next_time = min(future_times)
        if next_time >= horizon_ms:
            now = horizon_ms
        else:
            now = next_time

    trace.sort(key=lambda x: (x["dispatch_ms"], x["server"]))
    dropped.sort(key=lambda x: str(x["id"]))

    served_ms = {f: 0.0 for f in flow_weights}
    for t in trace:
        fl = t["flow"]
        if fl not in served_ms:
            served_ms[fl] = 0.0
        served_ms[fl] += t["service_ms"]

    return {
        "trace": trace,
        "served_ms": served_ms,
        "dropped": dropped,
    }


def compute_metrics(
    result: Dict[str, Any],
    flow_weights: Dict[str, float],
    servers: int,
    horizon_ms: float,
) -> Dict[str, float]:
    trace = result["trace"]
    served_ms = result["served_ms"]

    # 1. 公平性 Jain 指数
    ratios = []
    for f, w in flow_weights.items():
        weight = float(w) if float(w) > 0 else 1.0
        ratios.append(float(served_ms.get(f, 0.0)) / weight)
    n = len(ratios)
    sum_r = sum(ratios)
    sum_sq = sum(r * r for r in ratios)
    denom = n * sum_sq
    jain_index = (sum_r * sum_r) / denom if denom > 0 else 0.0

    # 2. 归一化吞吐
    total_useful = sum(t["service_ms"] for t in trace)
    capacity = servers * horizon_ms
    norm_throughput = (total_useful / capacity) * 100.0 if capacity > 0 else 0.0

    # 3. 平均等待时间
    mean_wait = (sum(t["wait_ms"] for t in trace) / len(trace)) if trace else 0.0

    return {
        "jain": jain_index,
        "throughput": norm_throughput,
        "mean_wait": mean_wait,
    }


def run_experiment(request: Dict[str, Any]) -> Dict[str, Any]:
    data = request.get("data", {})
    jobs = data.get("jobs", [])
    flow_weights = data.get("flow_weights", {})
    servers = int(data.get("servers", 1))
    setup_ms = float(data.get("setup_ms", 0.0))
    horizon_ms = float(data.get("horizon_ms", 0.0))

    baseline_res = simulate_scheduling(
        jobs, flow_weights, servers, setup_ms, horizon_ms, policy="fifo"
    )
    candidate_res = simulate_scheduling(
        jobs, flow_weights, servers, setup_ms, horizon_ms, policy="fair"
    )

    return {
        "baseline": baseline_res,
        "candidate": candidate_res,
        "details": {},
    }
