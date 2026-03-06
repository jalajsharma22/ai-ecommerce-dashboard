from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import numpy as np
from flask import jsonify




app = Flask(__name__, template_folder="templates")
app.secret_key = "secretkey"

# ================= DATABASE INIT =================
if not os.path.exists("database.db"):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    """)

    # Default Admin
    c.execute("INSERT INTO users (username,password,role) VALUES ('admin','admin123','admin')")
    conn.commit()
    conn.close()

conn = sqlite3.connect("database.db", check_same_thread=False)
c = conn.cursor()

# ================= LOGIN =================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        c.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p))
        user = c.fetchone()

        if user:
            session["user"] = u
            session["role"] = user[3]
            return redirect("/dashboard")
        else:
            return render_template("login.html", error="Invalid Credentials")

    return render_template("login.html")

# ================= SIGNUP =================
@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        try:
            c.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)", (u,p,"shopkeeper"))
            conn.commit()
            return redirect("/")
        except:
            return render_template("signup.html", error="Username already exists")

    return render_template("signup.html")

# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    transactions = pd.read_csv("data/transactions.csv")
    products = pd.read_csv("data/products.csv")

    total_sales = int(transactions["quantity"].sum())

    trending = (
        transactions.groupby("product_id", as_index=False)["quantity"]
        .sum()
        .sort_values("quantity", ascending=False)
        .head(5)
    )

    trending = trending.merge(products, on="product_id", how="left")

    if session["role"] == "admin":

        total_users = c.execute(
            "SELECT COUNT(*) FROM users WHERE role='shopkeeper'"
        ).fetchone()[0]

        shopkeepers = c.execute(
            "SELECT id, username FROM users WHERE role='shopkeeper'"
        ).fetchall()

        return render_template(
            "admin_dashboard.html",
            total_sales=total_sales,
            total_users=total_users,
            trending_products=trending.to_dict(orient="records"),
            shopkeepers=shopkeepers
        )

    else:
        trending["recommended_stock"] = (trending["quantity"] * 1.2).astype(int)

        return render_template(
            "shop_dashboard.html",
            total_sales=total_sales,
            trending_products=trending.to_dict(orient="records")
        )

# ================= ANALYTICS =================

@app.route("/analytics")
def analytics():
    if "user" not in session:
        return redirect("/")

    transactions = pd.read_csv("data/transactions.csv")
    products = pd.read_csv("data/products.csv")

    merged = transactions.merge(products, on="product_id", how="inner")

    # 🔥 debug
    print("TOTAL MERGED:", len(merged))

    merged["date"] = pd.to_datetime(merged["date"])
    merged["revenue"] = merged["quantity"] * merged["price"]

    # -------- CATEGORY SALES --------

    category_data = (
        merged.groupby("category")["quantity"]
        .sum()
        .reset_index()
    )

    print("CATEGORY COUNT:", len(category_data))

    category_labels = category_data["category"].tolist()
    category_values = category_data["quantity"].tolist()

    # -------- MONTHLY REVENUE --------

    monthly = (
        merged.groupby(merged["date"].dt.to_period("M"))["revenue"]
        .sum()
        .reset_index()
    )

    monthly["date"] = monthly["date"].astype(str)

    monthly_labels = monthly["date"].tolist()
    monthly_values = monthly["revenue"].tolist()

    # -------- BEST MONTH --------

    best_row = monthly.sort_values("revenue", ascending=False).iloc[0]

    best_month = best_row["date"]
    best_revenue = int(best_row["revenue"])

    # -------- TOTAL REVENUE --------

    total_revenue = int(merged["revenue"].sum())

    # -------- AVG MONTHLY REVENUE --------

    avg_monthly_revenue = int(monthly["revenue"].mean())

    return render_template(
        "analytics.html",
        category_labels=category_labels,
        category_values=category_values,
        monthly_labels=monthly_labels,
        monthly_values=monthly_values,
        best_month=best_month,
        best_revenue=best_revenue,
        total_revenue=total_revenue,
        avg_monthly_revenue=avg_monthly_revenue
    )

# ================= AI INSIGHT =================






@app.route("/ai")
def ai():

    if "user" not in session:
        return redirect("/")

    transactions = pd.read_csv("data/transactions.csv")
    products = pd.read_csv("data/products.csv")

    transactions["date"] = pd.to_datetime(transactions["date"])

    insights = []
    chart_data = {}

    # ===== TOP 3 PRODUCTS =====

    top_products = (
        transactions.groupby("product_id")["quantity"]
        .sum()
        .sort_values(ascending=False)
        .head(3)
        .index
    )

    chart_labels = []
    chart_datasets = []

    for pid in top_products:

        product_row = products[products["product_id"] == pid]

        if product_row.empty:
            continue

        name = product_row.iloc[0]["product_name"]

        product_data = transactions[transactions["product_id"] == pid]

        daily_sales = (
            product_data.groupby("date")["quantity"]
            .sum()
            .reset_index()
            .sort_values("date")
        )

        if len(daily_sales) < 10:
            continue

        daily_sales["day_index"] = np.arange(len(daily_sales))

        X = daily_sales[["day_index"]]
        y = daily_sales["quantity"]

        model = RandomForestRegressor(n_estimators=100)

        model.fit(X, y)

        future_days = np.arange(len(daily_sales), len(daily_sales)+7).reshape(-1,1)

        prediction = model.predict(future_days)

        next_week_demand = int(prediction.sum())

        avg_daily = y.mean()

        reorder_qty = int(next_week_demand * 1.15)

        # ===== RISK LEVEL =====

        if next_week_demand > avg_daily * 7 * 1.2:
            risk = "🔴 High Growth - Increase Stock"

        elif next_week_demand > avg_daily * 7:
            risk = "🟡 Moderate Growth"

        else:
            risk = "🟢 Stable"

        insights.append({
            "name": name,
            "current_avg": int(avg_daily),
            "predicted_week": next_week_demand,
            "reorder": reorder_qty,
            "risk": risk
        })

        chart_labels = daily_sales["date"].dt.strftime("%Y-%m-%d").tolist()

        chart_datasets.append({
            "label": name,
            "data": y.tolist(),
        })

    # ===== CATEGORY ANALYSIS =====

    merged = transactions.merge(products,on="product_id")

    category_sales = (
        merged.groupby("category")["quantity"]
        .sum()
        .sort_values(ascending=False)
    )

    top_category = category_sales.index[0]

    low_category = category_sales.index[-1]

    # ===== BUSINESS ADVISOR =====

    business_insights = [

        f"📈 Highest demand category: {top_category}",

        f"⚠️ Lowest demand category: {low_category}",

        f"💡 AI Advice: Increase stock for {top_category} products",

        f"💰 AI Strategy: Offer discounts on {low_category} category",

        "🚀 AI Strategy: Focus marketing on trending products"
    ]

    chart_data = {
        "labels": chart_labels,
        "datasets": chart_datasets
    }

    return render_template(
        "ai.html",
        insights=insights,
        chart_data=chart_data,
        business_insights=business_insights
    )

@app.route("/recommendations")
def recommendations():

    if "user" not in session:
        return redirect("/")

    transactions = pd.read_csv("data/transactions.csv")
    products = pd.read_csv("data/products.csv")

    recommendations_list = []

    top_products = (
        transactions.groupby("product_id")["quantity"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
        .index
    )

    for pid in top_products:

        product_row = products[products["product_id"] == pid]

        if product_row.empty:
            continue

        product_name = product_row.iloc[0]["product_name"]

        similar_products = products.sample(3)

        rec_names = similar_products["product_name"].tolist()

        recommendations_list.append({
            "product": product_name,
            "recommended": rec_names
        })

    print("RECOMMENDATION DATA:", recommendations_list)

    return render_template(
        "recommendations.html",
        recommendations=recommendations_list
    )

# ================= USERS =================
@app.route("/users")
def users():
    if "user" not in session:
        return redirect("/")

    if session["role"] != "admin":
        return redirect("/dashboard")

    shopkeepers = c.execute(
        "SELECT id, username FROM users WHERE role='shopkeeper'"
    ).fetchall()

    return render_template("users.html", shopkeepers=shopkeepers)

# ================= DELETE USER =================
@app.route("/delete_user/<int:user_id>")
def delete_user(user_id):
    if "user" not in session or session["role"] != "admin":
        return redirect("/")

    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()

    return redirect("/dashboard")


# ================= AI CHAT ASSISTANT =================



# ================= AI CHAT ASSISTANT =================

# ================= AI ASSISTANT =================



@app.route("/ai_chat", methods=["POST"])
def ai_chat():

    data = request.get_json()
    question = data.get("message","").lower()

    transactions = pd.read_csv("data/transactions.csv")
    products = pd.read_csv("data/products.csv")

    merged = transactions.merge(products, on="product_id")

    # TOTAL SALES
    if "sales" in question:

        total_sales = int(merged["quantity"].sum())

        reply = f"Total sales across all products are {total_sales} units."

    # TRENDING PRODUCT
    elif "trending" in question or "top product" in question:

        top = merged.groupby("product_name")["quantity"].sum().sort_values(ascending=False).head(1)

        reply = f"{top.index[0]} is currently the most trending product."

    # BEST CATEGORY
    elif "category" in question:

        cat = merged.groupby("category")["quantity"].sum().sort_values(ascending=False).head(1)

        reply = f"The best performing category is {cat.index[0]}."

    # STOCK ADVICE
    elif "stock" in question:

        demand = merged.groupby("product_name")["quantity"].sum().sort_values(ascending=False).head(1)

        reply = f"Stock for {demand.index[0]} should be increased due to high demand."

    # BUSINESS ADVICE
    elif "advice" in question or "strategy" in question:

        cat = merged.groupby("category")["quantity"].sum().sort_values(ascending=False)

        reply = f"Focus marketing on {cat.index[0]} category and offer discounts on {cat.index[-1]} category."

    else:

        reply = "Ask about sales, trending products, category performance, stock advice, or business strategy."

    return jsonify({"reply": reply})

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
    

