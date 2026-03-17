import axios from 'axios';

const api = axios.create({
    baseURL: 'http://localhost:8000/api',
});

export const discoverLeads = async (query) => {
    const response = await api.post('/discover', { query });
    return response.data;
};

export const getLeads = async (params) => {
    const response = await api.get('/leads', { params });
    return response.data;
};

export const getLead = async (id) => {
    const response = await api.get(`/leads/${id}`);
    return response.data;
};

export const runAudit = async (id) => {
    const response = await api.post(`/audit/${id}`);
    return response.data;
};

export const updateLeadStatus = async (id, status) => {
    const response = await api.patch(`/leads/${id}`, { status });
    return response.data;
};

export const generateEmail = async (id) => {
    const response = await api.post(`/generate-email/${id}`);
    return response.data;
};

export default api;
