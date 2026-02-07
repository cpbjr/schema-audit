import React, { useState } from 'react';
import { discoverLeads } from '../api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Search, Loader2 } from 'lucide-react';

export default function Discovery() {
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!query.trim()) return;

        setLoading(true);
        setError(null);
        setResult(null);

        try {
            const data = await discoverLeads(query);
            setResult(data);
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to discover leads');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="flex flex-col space-y-2">
                <h2 className="text-3xl font-bold tracking-tight">Discovery</h2>
                <p className="text-muted-foreground">Find new businesses using Google Places API.</p>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Search for Leads</CardTitle>
                </CardHeader>
                <CardContent>
                    <form onSubmit={handleSearch} className="flex gap-4">
                        <Input
                            placeholder="e.g. Plumbers in Eagle, ID"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            className="flex-1"
                        />
                        <Button type="submit" disabled={loading}>
                            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                            Search
                        </Button>
                    </form>

                    {error && (
                        <div className="mt-4 p-4 text-sm text-red-500 bg-red-50 rounded-md">
                            {error}
                        </div>
                    )}

                    {result && (
                        <div className="mt-4 p-4 bg-green-50 text-green-700 rounded-md">
                            <p className="font-semibold">Success!</p>
                            <p>{result.message}</p>
                            <p className="text-sm mt-1">Total businesses in database: {result.total_count}</p>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
