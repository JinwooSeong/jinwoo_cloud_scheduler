import request from '@/utils/request';

export function login(data) {
    return request({
        url: '/user/login/',
        method: 'post',
        data
    });
}

export function updateUserInfo(email, password) {
    return request({
        url: '/user/',
        method: 'put',
        data: {
            password: password,
            email: email
        }
    });
}

export function getInfo() {
    return request({
        url: '/user/',
        method: 'get'
    });
}

export function logout(token) {
    return request({
        url: '/user/logout/',
        method: 'get',
        params: { token }
    });
}

export function signup(data) {
    return request({
        url: '/user/',
        method: 'post',
        data
    });
}
