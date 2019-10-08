const Config = {
    dev: {
        apiUrl: 'http://127.0.0.1:8000/',
        wsUrl: 'ws://127.0.0.1:8000/',
        routerBaseUrl: '/'
    },
    prod: {
        apiUrl: 'https://cloud-scheduler-sigquit.app.secoder.net/api/',
        wsUrl: 'ws://cloud-scheduler-sigquit.app.secoder.net/api/',
        routerBaseUrl: '/'
    }
};

export default Config;
