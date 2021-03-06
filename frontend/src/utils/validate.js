
export function isExternal(path) {
    return /^(https?:|mailto:|tel:)/.test(path);
}

export function validateEmail(email) {
    return /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/.test(email);
}

export function validatePath(path) {
    return /^\/?([^\\/:*?"<>|]+\/?)+$/.test(path);
}
