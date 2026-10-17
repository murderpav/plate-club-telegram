import os, sqlite3, secrets, hashlib, hmac, time, json, random, re, urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT=os.path.dirname(os.path.abspath(__file__))
DB_PATH=os.path.join(ROOT,"plate_club.db")
app=FastAPI(title="PLATE CLUB API", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

LETTERS="АВЕКМНОРСТУХ"
REGIONS="01 02 10 11 16 21 23 24 26 34 36 38 50 52 54 59 61 63 64 66 72 73 74 76 77 78 86 93 96 97 98 99 102 116 124 134 150 154 161 163 174 177 178 190 196 197 198 199 777 797 799".split()
PREMIUM={"77","78","97","98","99","177","178","197","198","199","777","797","799"}
SPECIAL={"001","007","002","003","100","200","300","500","700","900"}
LUCKY=["001","007","777","999","000","111","555","100","123","700","888","121","343"]
RARITY=["Обычный","Редкий","Эпический","Легендарный"]
RARITY_EMOJI=["⚪","🔵","🟣","🟡"]
START_COINS=500

@contextmanager
def db():
    con=sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory=sqlite3.Row
    try:
        yield con
        con.commit()
    finally: con.close()

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
          salt TEXT NOT NULL, password_hash TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 500,
          xp INTEGER NOT NULL DEFAULT 0, spins INTEGER NOT NULL DEFAULT 0, sold INTEGER NOT NULL DEFAULT 0,
          last_daily INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0, last_daily_day TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL, profile_frame TEXT NOT NULL DEFAULT 'gold');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS plates(
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL, plate TEXT NOT NULL,
          region TEXT NOT NULL, rarity INTEGER NOT NULL, value INTEGER NOT NULL, protected INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS listings(
          id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER NOT NULL, plate_id INTEGER NOT NULL UNIQUE,
          price INTEGER NOT NULL, created_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS achievements(
          user_id INTEGER NOT NULL, code TEXT NOT NULL, unlocked_at INTEGER NOT NULL, PRIMARY KEY(user_id,code));
        CREATE TABLE IF NOT EXISTS quest_claims(
          user_id INTEGER NOT NULL, day TEXT NOT NULL, code TEXT NOT NULL, claimed_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,day,code));
        CREATE TABLE IF NOT EXISTS collection_claims(
          user_id INTEGER NOT NULL, region TEXT NOT NULL, claimed_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,region));
        CREATE TABLE IF NOT EXISTS season_claims(
          user_id INTEGER NOT NULL, tier INTEGER NOT NULL, claimed_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,tier));
        CREATE INDEX IF NOT EXISTS idx_plates_owner ON plates(owner_id);
        CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
        """)
init_db()
with db() as _c:
    try:
        _c.execute("ALTER TABLE users ADD COLUMN profile_frame TEXT NOT NULL DEFAULT 'gold'")
    except sqlite3.OperationalError:
        pass

class TelegramAuth(BaseModel):
    initData: str = Field(min_length=1, max_length=8192)

def verify_telegram_init_data(init_data: str, bot_token: str):
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None
        auth_date = int(pairs.get("auth_date", "0"))
        # Reject stale launch payloads; Telegram WebApp initData should be freshly issued.
        if auth_date <= 0 or time.time() - auth_date > 86400 or auth_date - time.time() > 60:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        tg_user = json.loads(pairs.get("user", "{}"))
        if not tg_user.get("id"):
            return None
        return tg_user
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

@app.post("/api/auth/telegram")
def auth_telegram(body: TelegramAuth):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise HTTPException(503, "Telegram пока не настроен: добавь TELEGRAM_BOT_TOKEN в .env")
    tg_user = verify_telegram_init_data(body.initData, bot_token)
    if not tg_user:
        raise HTTPException(401, "Не удалось проверить данные Telegram. Открой игру через кнопку бота заново.")
    # Stable internal username; Telegram display names can change and are not unique.
    username = "tg" + str(int(tg_user["id"]))
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not u:
            salt, digest = hash_password(secrets.token_urlsafe(32))
            cur = c.execute("INSERT INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)", (username, salt, digest, int(time.time())))
            uid = cur.lastrowid
            # Give new Telegram players a starter plate so the garage is not empty.
            p = gen_plate()
            c.execute("INSERT INTO plates(owner_id,plate,region,rarity,value,created_at) VALUES(?,?,?,?,?,?)", (uid,p["plate"],p["region"],p["rarity"],p["value"],int(time.time())))
            u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token,u["id"],int(time.time())))
    return {"token": token, "user": public_user(u), "telegram": {"id": tg_user["id"], "first_name": tg_user.get("first_name", "Игрок")}}

class Credentials(BaseModel):
    username: str = Field(min_length=3,max_length=20,pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8,max_length=128)

class ListRequest(BaseModel):
    plate_id: int
    price: int = Field(ge=1, le=100000000)

def hash_password(password, salt=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240000).hex()
    return salt,digest

def user_from_token(authorization):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"Войди в аккаунт")
    token=authorization.split(" ",1)[1].strip()
    with db() as c:
        row=c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",(token,)).fetchone()
    if not row: raise HTTPException(401,"Сессия истекла, войди снова")
    return row

def public_user(u):
    with db() as c:
        count=c.execute("SELECT COUNT(*) n FROM plates WHERE owner_id=?",(u["id"],)).fetchone()["n"]
        value=c.execute("SELECT COALESCE(SUM(value),0) n FROM plates WHERE owner_id=?",(u["id"],)).fetchone()["n"]
        rare=c.execute("SELECT COUNT(*) n FROM plates WHERE owner_id=? AND rarity>=2",(u["id"],)).fetchone()["n"]
        best=c.execute("SELECT MAX(rarity) r FROM plates WHERE owner_id=?",(u["id"],)).fetchone()["r"]
    level=u["xp"]//250+1
    ranks=["НОВИЧОК","СОБИРАТЕЛЬ","ОХОТНИК","ЭКСПЕРТ","ЛЕГЕНДА"]
    return {"id":u["id"],"username":u["username"],"coins":u["coins"],"xp":u["xp"],"level":level,
      "rank":ranks[min(4,(level-1)//3)],"spins":u["spins"],"sold":u["sold"],"plate_count":count,
      "garage_value":value,"rare_count":rare,"best_rarity":best,"streak":u["streak"],"last_daily_day":u["last_daily_day"],"profile_frame":u["profile_frame"]}

def gen_plate():
    l1=random.choice(LETTERS)
    digits=random.choice(LUCKY) if random.random()<0.1 else f"{random.randint(0,999):03d}"
    l23=random.choice(LETTERS)+random.choice(LETTERS)
    region=random.choice(REGIONS)
    pts=0
    if len(set(digits))==1:
        pts+=2
        if digits=="777": pts+=1
    if digits in SPECIAL: pts+=3 if digits in {"001","007"} else 2
    if digits[0]==digits[2] and len(set(digits))>1: pts+=1
    if l1==l23[0]==l23[1]: pts+=3
    elif l23[0]==l23[1]: pts+=1
    if region in PREMIUM: pts+=1
    if pts==0: rarity,value=0,random.randint(30,70)
    elif pts<=2: rarity,value=1,random.randint(150,300)
    elif pts<=4: rarity,value=2,random.randint(600,1200)
    else: rarity,value=3,random.randint(3000,6000)
    return {"plate":f"{l1}{digits}{l23}","region":region,"rarity":rarity,"value":value}

def add_xp(c,user_id,amount):
    c.execute("UPDATE users SET xp=xp+? WHERE id=?",(amount,user_id))

def check_achievements(c, uid):
    u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    count=c.execute("SELECT COUNT(*) n FROM plates WHERE owner_id=?",(uid,)).fetchone()["n"]
    legendary=c.execute("SELECT COUNT(*) n FROM plates WHERE owner_id=? AND rarity=3",(uid,)).fetchone()["n"]
    rare=c.execute("SELECT COUNT(*) n FROM plates WHERE owner_id=? AND rarity>=2",(uid,)).fetchone()["n"]
    checks={"first_spin":u["spins"]>=1,"ten_plates":count>=10,"rare_find":rare>=1,"legend":legendary>=1,"first_sale":u["sold"]>=1,"twenty_five":u["spins"]>=25,"streak_7":u["streak"]>=7}
    for code,ok in checks.items():
        if ok: c.execute("INSERT OR IGNORE INTO achievements(user_id,code,unlocked_at) VALUES(?,?,?)",(uid,code,int(time.time())))

@app.get("/")
def home():
    return FileResponse(os.path.join(ROOT,"index.html"))

@app.get("/api/health")
def health():
    return {"ok":True,"app":"PLATE CLUB","version":"3.0.0"}

@app.post("/api/register")
def register(body:Credentials):
    username=body.username.lower()
    salt,digest=hash_password(body.password)
    with db() as c:
        if c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone():
            raise HTTPException(409,"Такой логин уже занят")
        cur=c.execute("INSERT INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)",(username,salt,digest,int(time.time())))
        uid=cur.lastrowid
        token=secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",(token,uid,int(time.time())))
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    return {"token":token,"user":public_user(u)}

@app.post("/api/login")
def login(body:Credentials):
    username=body.username.lower()
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        if not u: raise HTTPException(401,"Неверный логин или пароль")
        _,digest=hash_password(body.password,u["salt"])
        if not hmac.compare_digest(digest,u["password_hash"]): raise HTTPException(401,"Неверный логин или пароль")
        token=secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",(token,u["id"],int(time.time())))
    return {"token":token,"user":public_user(u)}

@app.post("/api/logout")
def logout(authorization:str|None=Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        with db() as c: c.execute("DELETE FROM sessions WHERE token=?",(authorization.split(" ",1)[1].strip(),))
    return {"ok":True}

@app.get("/api/me")
def me(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization)
    return {"user":public_user(u)}

@app.get("/api/state")
def state(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        plates=[dict(r) for r in c.execute("SELECT id,plate AS num,region AS reg,rarity AS r,value AS v,protected FROM plates WHERE owner_id=? ORDER BY value DESC",(uid,)).fetchall()]
        ach=[r["code"] for r in c.execute("SELECT code FROM achievements WHERE user_id=?",(uid,)).fetchall()]
        claims=[r["code"] for r in c.execute("SELECT code FROM quest_claims WHERE user_id=? AND day=?",(uid,datetime.now(timezone.utc).date().isoformat())).fetchall()]
    return {"user":public_user(u),"plates":plates,"achievements":ach,"claims":claims,"server_time":int(time.time())}

@app.post("/api/spin")
def spin(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if u["coins"]<100: raise HTTPException(400,"Не хватает монет — забери ежедневный бонус")
        p=gen_plate()
        c.execute("UPDATE users SET coins=coins-100,spins=spins+1,xp=xp+? WHERE id=?",(25+p["rarity"]*20,uid))
        cur=c.execute("INSERT INTO plates(owner_id,plate,region,rarity,value,created_at) VALUES(?,?,?,?,?,?)",(uid,p["plate"],p["region"],p["rarity"],p["value"],int(time.time())))
        p.update({"id":cur.lastrowid,"num":p["plate"],"reg":p["region"],"r":p["rarity"],"v":p["value"]})
        check_achievements(c,uid)
        coins=c.execute("SELECT coins FROM users WHERE id=?",(uid,)).fetchone()["coins"]
    return {"plate":p,"coins":coins,"rarity_name":RARITY[p["rarity"]]}

@app.post("/api/sell/{plate_id}")
def sell(plate_id:int,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        p=c.execute("SELECT * FROM plates WHERE id=? AND owner_id=?",(plate_id,uid)).fetchone()
        if not p: raise HTTPException(404,"Номер не найден в гараже")
        if p["protected"]: raise HTTPException(400,"Этот номер защищён музеем редкостей")
        if c.execute("SELECT id FROM listings WHERE plate_id=? AND status='active'",(plate_id,)).fetchone():
            raise HTTPException(400,"Сначала снимите номер с рынка")
        c.execute("DELETE FROM plates WHERE id=?",(plate_id,))
        c.execute("UPDATE users SET coins=coins+?,sold=sold+1,xp=xp+5 WHERE id=?",(p["value"],uid))
        check_achievements(c,uid)
        coins=c.execute("SELECT coins FROM users WHERE id=?",(uid,)).fetchone()["coins"]
    return {"ok":True,"coins":coins,"sold_value":p["value"]}

@app.post("/api/daily")
def daily(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]; today=datetime.now(timezone.utc).date()
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if u["last_daily_day"]==today.isoformat(): raise HTTPException(400,"Ежедневный бонус уже получен")
        yesterday=(today.fromordinal(today.toordinal()-1)).isoformat()
        streak=u["streak"]+1 if u["last_daily_day"]==yesterday else 1
        c.execute("UPDATE users SET coins=coins+200,xp=xp+15,last_daily=?,last_daily_day=?,streak=? WHERE id=?",(int(time.time()),today.isoformat(),streak,uid))
        check_achievements(c,uid)
    return {"ok":True,"reward":200,"streak":streak}

@app.post("/api/protect/{plate_id}")
def protect(plate_id:int,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        p=c.execute("SELECT * FROM plates WHERE id=? AND owner_id=?",(plate_id,uid)).fetchone()
        if not p: raise HTTPException(404,"Номер не найден")
        c.execute("UPDATE plates SET protected=? WHERE id=?",(0 if p["protected"] else 1,plate_id))
        result=0 if p["protected"] else 1
    return {"protected":bool(result)}

@app.post("/api/market/list")
def create_listing(body:ListRequest,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        p=c.execute("SELECT * FROM plates WHERE id=? AND owner_id=?",(body.plate_id,uid)).fetchone()
        if not p: raise HTTPException(404,"Номер не найден")
        if p["protected"]: raise HTTPException(400,"Сначала убери номер из музея")
        if c.execute("SELECT id FROM listings WHERE plate_id=? AND status='active'",(body.plate_id,)).fetchone(): raise HTTPException(400,"Номер уже выставлен")
        c.execute("INSERT INTO listings(seller_id,plate_id,price,created_at,status) VALUES(?,?,?,?, 'active')",(uid,body.plate_id,body.price,int(time.time())))
    return {"ok":True}

@app.get("/api/market")
def market():
    with db() as c:
        rows=c.execute("""SELECT l.id AS listing_id,l.price,l.created_at,p.id AS plate_id,p.plate AS num,p.region AS reg,p.rarity AS r,p.value AS v,u.username AS seller
          FROM listings l JOIN plates p ON p.id=l.plate_id JOIN users u ON u.id=l.seller_id
          WHERE l.status='active' ORDER BY l.created_at DESC LIMIT 100""").fetchall()
    return {"listings":[dict(r) for r in rows]}

@app.post("/api/market/buy/{listing_id}")
def buy_listing(listing_id:int,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        l=c.execute("SELECT l.*,p.owner_id FROM listings l JOIN plates p ON p.id=l.plate_id WHERE l.id=? AND l.status='active'",(listing_id,)).fetchone()
        if not l: raise HTTPException(404,"Лот уже недоступен")
        if l["seller_id"]==uid: raise HTTPException(400,"Нельзя купить собственный лот")
        buyer=c.execute("SELECT coins FROM users WHERE id=?",(uid,)).fetchone()
        if buyer["coins"]<l["price"]: raise HTTPException(400,"Не хватает монет")
        # Atomic update and transfer in one transaction
        c.execute("UPDATE users SET coins=coins-? WHERE id=?",(l["price"],uid))
        c.execute("UPDATE users SET coins=coins+? WHERE id=?",(l["price"],l["seller_id"]))
        c.execute("UPDATE plates SET owner_id=? WHERE id=?",(uid,l["plate_id"]))
        c.execute("UPDATE listings SET status='sold' WHERE id=?",(listing_id,))
        add_xp(c,uid,20); check_achievements(c,uid)
    return {"ok":True}

@app.post("/api/market/cancel/{listing_id}")
def cancel_listing(listing_id:int,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        l=c.execute("SELECT * FROM listings WHERE id=? AND seller_id=? AND status='active'",(listing_id,uid)).fetchone()
        if not l: raise HTTPException(404,"Лот не найден")
        c.execute("UPDATE listings SET status='cancelled' WHERE id=?",(listing_id,))
    return {"ok":True}


@app.post("/api/quest/{code}")
def claim_quest(code:str,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]; today=datetime.now(timezone.utc).date().isoformat()
    quests={
      "spin3":{"reward":150,"goal":3,"kind":"spin"},
      "rare1":{"reward":250,"goal":1,"kind":"rare"},
      "sell1":{"reward":100,"goal":1,"kind":"sell"}
    }
    q=quests.get(code)
    if not q: raise HTTPException(404,"Задание не найдено")
    with db() as c:
        if c.execute("SELECT 1 FROM quest_claims WHERE user_id=? AND day=? AND code=?",(uid,today,code)).fetchone():
            raise HTTPException(400,"Награда за это задание уже получена сегодня")
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if q["kind"]=="spin": progress=u["spins"]
        elif q["kind"]=="sell": progress=u["sold"]
        else:
            progress=1 if c.execute("SELECT 1 FROM achievements WHERE user_id=? AND code='rare_find'",(uid,)).fetchone() else 0
        if progress<q["goal"]: raise HTTPException(400,"Задание ещё не выполнено")
        c.execute("INSERT INTO quest_claims(user_id,day,code,claimed_at) VALUES(?,?,?,?)",(uid,today,code,int(time.time())))
        c.execute("UPDATE users SET coins=coins+?,xp=xp+20 WHERE id=?",(q["reward"],uid))
    return {"ok":True,"reward":q["reward"]}


@app.post("/api/case/{case_code}")
def open_case(case_code:str,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    cases={"street":250,"rare":1000,"legend":2500}
    if case_code not in cases: raise HTTPException(404,"Кейс не найден")
    cost=cases[case_code]
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if u["coins"]<cost: raise HTTPException(400,"Не хватает монет")
        p=gen_plate()
        if case_code=="rare" and p["rarity"]<2:
            p["rarity"]=2;p["value"]=random.randint(600,1200)
        if case_code=="legend" and p["rarity"]<2:
            p["rarity"]=3;p["value"]=random.randint(3000,6000)
        c.execute("UPDATE users SET coins=coins-?,xp=xp+? WHERE id=?",(cost,30+p["rarity"]*15,uid))
        cur=c.execute("INSERT INTO plates(owner_id,plate,region,rarity,value,created_at) VALUES(?,?,?,?,?,?)",(uid,p["plate"],p["region"],p["rarity"],p["value"],int(time.time())))
        p.update({"id":cur.lastrowid,"num":p["plate"],"reg":p["region"],"r":p["rarity"],"v":p["value"]})
        check_achievements(c,uid)
    return {"ok":True,"plate":p,"cost":cost}

@app.post("/api/profile/frame/{frame}")
def set_frame(frame:str,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    frames={"gold":0,"blue":300,"purple":500,"legendary":1000}
    if frame not in frames: raise HTTPException(400,"Неизвестная рамка")
    cost=frames[frame]
    with db() as c:
        u=c.execute("SELECT coins,profile_frame FROM users WHERE id=?",(uid,)).fetchone()
        if u["profile_frame"]==frame: return {"ok":True,"frame":frame,"cost":0}
        if u["coins"]<cost: raise HTTPException(400,"Не хватает монет")
        c.execute("UPDATE users SET coins=coins-?,profile_frame=? WHERE id=?",(cost,frame,uid))
    return {"ok":True,"frame":frame,"cost":cost}

@app.post("/api/collections/claim/{region}")
def claim_collection(region:str,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    with db() as c:
        count=c.execute("SELECT COUNT(*) n FROM plates WHERE owner_id=? AND region=?",(uid,region)).fetchone()["n"]
        if count<5: raise HTTPException(400,"Нужно собрать 5 номеров этого региона")
        if c.execute("SELECT 1 FROM collection_claims WHERE user_id=? AND region=?",(uid,region)).fetchone():
            raise HTTPException(400,"Награда за эту серию уже получена")
        c.execute("INSERT INTO collection_claims(user_id,region,claimed_at) VALUES(?,?,?)",(uid,region,int(time.time())))
        c.execute("UPDATE users SET coins=coins+500,xp=xp+100 WHERE id=?",(uid,))
    return {"ok":True,"reward":500,"xp":100}

@app.get("/api/season")
def season(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization)
    tiers=[{"tier":1,"xp":100,"reward":150},{"tier":2,"xp":250,"reward":300},{"tier":3,"xp":500,"reward":600},{"tier":4,"xp":1000,"reward":1200}]
    with db() as c:
        claimed=[r["tier"] for r in c.execute("SELECT tier FROM season_claims WHERE user_id=?",(u["id"],)).fetchall()]
    return {"season":"SEASON 03","xp":u["xp"],"tiers":[{**t,"claimed":t["tier"] in claimed,"ready":u["xp"]>=t["xp"]} for t in tiers]}

@app.post("/api/season/claim/{tier}")
def claim_season(tier:int,authorization:str|None=Header(default=None)):
    u=user_from_token(authorization)
    rewards={1:(100,150),2:(250,300),3:(500,600),4:(1000,1200)}
    if tier not in rewards: raise HTTPException(404,"Уровень пропуска не найден")
    needed,reward=rewards[tier]
    with db() as c:
        if u["xp"]<needed: raise HTTPException(400,"Недостаточно сезонного опыта")
        if c.execute("SELECT 1 FROM season_claims WHERE user_id=? AND tier=?",(u["id"],tier)).fetchone():
            raise HTTPException(400,"Эта награда уже получена")
        c.execute("INSERT INTO season_claims(user_id,tier,claimed_at) VALUES(?,?,?)",(u["id"],tier,int(time.time())))
        c.execute("UPDATE users SET coins=coins+? WHERE id=?",(reward,u["id"]))
    return {"ok":True,"reward":reward}

@app.get("/api/leaderboard")
def leaderboard():
    with db() as c:
        rows=c.execute("""SELECT u.username,u.xp,u.spins,
          (SELECT COUNT(*) FROM plates p WHERE p.owner_id=u.id) AS plates,
          (SELECT COALESCE(SUM(p.value),0) FROM plates p WHERE p.owner_id=u.id) AS garage_value,
          (SELECT COALESCE(MAX(p.rarity),-1) FROM plates p WHERE p.owner_id=u.id) AS best_rarity
          FROM users u ORDER BY garage_value DESC,u.xp DESC LIMIT 50""").fetchall()
    return {"players":[dict(r) for r in rows]}

@app.get("/api/collections")
def collections(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization); uid=u["id"]
    regions=["66","96","77","78","99","777","02","74","50","197","196","174"]
    with db() as c:
        rows=c.execute("SELECT region,COUNT(*) n,MAX(rarity) best FROM plates WHERE owner_id=? GROUP BY region",(uid,)).fetchall()
    got={r["region"]:dict(r) for r in rows}
    result=[]
    for reg in regions:
        count=got.get(reg,{}).get("n",0)
        result.append({"region":reg,"count":count,"best_rarity":got.get(reg,{}).get("best"),"complete":count>=5})
    with db() as c:
        claimed=[r["region"] for r in c.execute("SELECT region FROM collection_claims WHERE user_id=?",(uid,)).fetchall()]
    for item in result: item["claimed"]=item["region"] in claimed
    return {"regions":result}

@app.get("/api/achievements")
def achievements(authorization:str|None=Header(default=None)):
    u=user_from_token(authorization)
    with db() as c:
        rows=c.execute("SELECT code,unlocked_at FROM achievements WHERE user_id=? ORDER BY unlocked_at DESC",(u["id"],)).fetchall()
    return {"unlocked":[dict(r) for r in rows]}

@app.get("/api/admin/summary")
def admin_summary(x_admin_key:str|None=Header(default=None)):
    secret=os.getenv("ADMIN_KEY","")
    if not secret or not x_admin_key or not hmac.compare_digest(secret,x_admin_key):
        raise HTTPException(403,"Доступ запрещён")
    with db() as c:
        return {"users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
                "plates":c.execute("SELECT COUNT(*) n FROM plates").fetchone()["n"],
                "active_listings":c.execute("SELECT COUNT(*) n FROM listings WHERE status='active'").fetchone()["n"]}
