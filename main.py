from flask import Flask
from server.gateway_agent import gateway_bp

def create_app():
    app = Flask(__name__)
    
    # Register Blueprints
    app.register_blueprint(gateway_bp)

    @app.route('/')
    def home():
        return "Hello, Flask!"

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
