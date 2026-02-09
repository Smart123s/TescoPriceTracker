from flask import Flask, render_template, request, abort
import database_manager as db
from datetime import datetime

app = Flask(__name__)

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M'):
    if value is None:
        return ""
    try:
        # Check if it's already a datetime object or string
        if isinstance(value, str):
            dt = datetime.fromisoformat(value)
        else:
            dt = value
        return dt.strftime(format)
    except:
        return value

@app.route('/')
def index():
    query = request.args.get('q')
    results = []
    if query:
        results = db.search_products(query)
    return render_template('index.html', results=results, query=query)

@app.route('/product/<tpnc>')
def product_detail(tpnc):
    product = db.get_product(tpnc)
    if not product:
        abort(404)
    
    history = db.get_price_history(tpnc)
    
    # Prepare data for chart
    dates = []
    prices = []
    clubcard_prices = []
    
    for h in reversed(history): # Chronological order
        d = h['timestamp']
        # If timestamp is string, parse it, if datetime, use it. 
        # SQLite generic connector returns strings usually.
        dates.append(d)
        prices.append(h['price_actual'])
        clubcard_prices.append(h['clubcard_price'] if h['clubcard_price'] else None)

    return render_template('product.html', product=product, history=history, dates=dates, prices=prices, clubcard_prices=clubcard_prices)

if __name__ == '__main__':
    # Ensure DB is ready
    db.init_db()
    app.run(debug=True, port=5000)
