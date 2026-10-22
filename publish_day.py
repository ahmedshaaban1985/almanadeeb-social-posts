# -*- coding: utf-8 -*-
"""
Daily publisher for Al-Manadeeb Creative Services.
Runs INSIDE the Composio remote workbench (helpers run_composio_tool / upload_local_file are preloaded).
Usage in workbench:
    import requests; exec(requests.get(RAW + "publish_day.py", timeout=60).text)
    report = publish(date="2026-10-24", dry_run=False)   # date in Asia/Qatar
"""
import json, os, datetime, requests, time

OWNER_REPO = "ahmedshaaban1985/almanadeeb-social-posts"
RAW = f"https://raw.githubusercontent.com/{OWNER_REPO}/main/"

CFG = {
    "facebook":  {"account": "facebook_lenny-relot", "page_id": "102403399125703"},
    "instagram": {"account": "instagram_causer-divest", "ig_user_id": "17841453552780071"},
    "linkedin":  [{"account": "linkedin_clio-booky",   "author": "urn:li:person:zCukMA44MW", "label": "Ahmed Shaaban"},
                  {"account": "linkedin_rumkin-aridge", "author": "urn:li:person:eEYGCtTcy8", "label": "Al Manadeeb Creative Services"}],
    "youtube":   {"account": "youtube_bully-ureal"},
}

def _ok(res, err):
    if err: return False, str(err)[:400]
    data = res.get("data") if isinstance(res, dict) else None
    if isinstance(res, dict) and res.get("successful") is False:
        return False, json.dumps(res, ensure_ascii=False)[:400]
    if isinstance(data, dict) and (data.get("http_error") or data.get("error")):
        return False, json.dumps(data, ensure_ascii=False)[:400]
    return True, data

def _find(d, keys):
    """depth-first search for the first key in keys"""
    if isinstance(d, dict):
        for k in keys:
            if k in d and d[k]: return d[k]
        for v in d.values():
            r = _find(v, keys)
            if r: return r
    elif isinstance(d, list):
        for v in d:
            r = _find(v, keys)
            if r: return r
    return None

def _download(url, path):
    r = requests.get(url, timeout=120); r.raise_for_status()
    open(path, "wb").write(r.content); return path

def _staged(path, mimetype):
    res, err = upload_local_file(path)
    if err: raise RuntimeError(f"upload_local_file failed: {err}")
    key = _find(res, ["s3key", "key"])
    if not key: raise RuntimeError(f"no s3key in upload result: {str(res)[:300]}")
    return {"name": os.path.basename(path), "mimetype": mimetype, "s3key": key}

def _li_escape(t):
    for ch in "()[]{}<>|~":
        t = t.replace(ch, "\\" + ch)
    return t

def publish(date=None, dry_run=False, only=None):
    if date is None:
        date = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).date().isoformat()
    sched = requests.get(RAW + "schedule.json", timeout=60).json()["days"]
    folder = sched.get(date)
    report = {"date": date, "folder": folder, "results": {}}
    if not folder:
        report["note"] = "No post scheduled for this date"; return report
    base = RAW + "posts/" + folder + "/"
    meta = requests.get(base + "post.json", timeout=60).json()
    f = meta["files"]
    img_url, story_url, video_url = base + f["post_jpg"], base + f["story_jpg"], base + f["video"]
    for u in (img_url, story_url, video_url):
        h = requests.head(u, timeout=60, allow_redirects=False)
        if h.status_code != 200: raise RuntimeError(f"Asset not reachable ({h.status_code}): {u}")
    cap = meta["caption"]
    want = lambda p: (only is None) or (p in only)
    R = report["results"]
    if dry_run:
        report["note"] = "dry run - assets reachable, nothing published"; return report

    # ---------- Facebook page photo
    if want("facebook"):
        res, err = run_composio_tool("FACEBOOK_CREATE_PHOTO_POST", {"page_id": CFG["facebook"]["page_id"], "url": img_url, "message": cap},
                                     account=CFG["facebook"]["account"])
        ok, d = _ok(res, err); R["facebook"] = {"ok": ok, "id": _find(d, ["post_id", "id"]) if ok else None, "err": None if ok else d}

    # ---------- Instagram: feed image, story, reel
    if want("instagram"):
        ig = CFG["instagram"]; acc = ig["account"]; uid = ig["ig_user_id"]
        ig_cap = cap.replace("#", "%23")   # per Composio tool doc
        def ig_pub(args, label, wait=90):
            res, err = run_composio_tool("INSTAGRAM_POST_IG_USER_MEDIA", dict(ig_user_id=uid, **args), account=acc)
            ok, d = _ok(res, err)
            if not ok: return {"ok": False, "err": d}
            cid = _find(d, ["id", "creation_id"])
            for attempt in range(3):
                res, err = run_composio_tool("INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH", {"ig_user_id": uid, "creation_id": str(cid), "max_wait_seconds": wait}, account=acc)
                ok, d2 = _ok(res, err)
                if ok: return {"ok": True, "id": _find(d2, ["id"])}
                time.sleep(15)
            return {"ok": False, "err": d2}
        R["instagram_feed"] = ig_pub({"image_url": img_url, "caption": ig_cap}, "feed", 60)
        R["instagram_story"] = ig_pub({"image_url": story_url, "media_type": "STORIES"}, "story", 60)
        R["instagram_reel"] = ig_pub({"video_url": video_url, "media_type": "REELS", "caption": ig_cap, "share_to_feed": False}, "reel", 170)
        # verify caption rendering on the feed post
        if R["instagram_feed"].get("ok"):
            res, err = run_composio_tool("INSTAGRAM_GET_IG_USER_MEDIA", {"ig_user_id": uid, "limit": 3, "fields": "id,caption,timestamp"}, account=acc)
            c = _find(res, ["caption"]) or ""
            R["instagram_caption_check"] = "OK" if ("#" in c and "%23" not in c) else f"CHECK: {c[-120:]}"

    # ---------- LinkedIn (both profiles)
    if want("linkedin"):
        jpg = _download(img_url, "/tmp/li.jpg"); media = _staged(jpg, "image/jpeg")
        for li in CFG["linkedin"]:
            res, err = run_composio_tool("LINKEDIN_CREATE_LINKED_IN_POST", {"author": li["author"], "commentary": _li_escape(cap), "images": [media], "visibility": "PUBLIC", "lifecycleState": "PUBLISHED"},
                                         account=li["account"])
            ok, d = _ok(res, err)
            pid = _find(d, ["x_restli_id", "id"]) if ok else None
            R["linkedin_" + li["label"]] = {"ok": bool(ok and pid), "id": pid, "err": None if ok else d}

    # ---------- YouTube Shorts
    if want("youtube"):
        try:
            mp4 = _download(video_url, "/tmp/yt.mp4"); vmedia = _staged(mp4, "video/mp4")
            title = (meta["yt_title"] + " #Shorts")[:100]
            desc = cap + "\n\n" + meta.get("hashtags", "")
            tags = ["المناديب المبدعون", "قطر", "الدوحة", "تخليص معاملات", "خدمات الشركات", "Qatar", "Doha", "PRO services", "Shorts"]
            res, err = run_composio_tool("YOUTUBE_UPLOAD_VIDEO", {"title": title, "description": desc, "tags": tags, "categoryId": "22", "privacyStatus": "public", "videoFilePath": vmedia},
                                         account=CFG["youtube"]["account"])
            ok, d = _ok(res, err); R["youtube"] = {"ok": ok, "id": _find(d, ["id"]) if ok else None, "err": None if ok else d}
        except Exception as e:
            R["youtube"] = {"ok": False, "err": str(e)[:300]}

    report["summary"] = {k: ("OK" if (isinstance(v, dict) and v.get("ok")) else v if isinstance(v, str) else "FAILED") for k, v in R.items()}
    report["manual_files"] = {"x_text": meta.get("x_text"), "post_jpg": img_url, "story_jpg": story_url, "video": video_url}
    return report
