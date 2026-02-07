import React, { useEffect, useState } from 'react';
import { getLeads, runAudit, updateLeadStatus } from '../api';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Loader2, PlayCircle, CheckCircle2, AlertTriangle, XCircle, Search, ExternalLink } from 'lucide-react';

export default function Leads() {
    const [leads, setLeads] = useState([]);
    const [loading, setLoading] = useState(true);
    const [auditLoading, setAuditLoading] = useState({});

    useEffect(() => {
        fetchLeads();
    }, []);

    const fetchLeads = async () => {
        try {
            const data = await getLeads();
            setLeads(data);
        } catch (error) {
            console.error('Failed to fetch leads', error);
        } finally {
            setLoading(false);
        }
    };

    const handleAudit = async (id) => {
        setAuditLoading((prev) => ({ ...prev, [id]: true }));
        try {
            await runAudit(id);
            await fetchLeads(); // Refresh to get results
        } catch (error) {
            console.error('Audit failed', error);
        } finally {
            setAuditLoading((prev) => ({ ...prev, [id]: false }));
        }
    };

    const handleStatusChange = async (id, newStatus) => {
        try {
            await updateLeadStatus(id, newStatus);
            setLeads((prev) =>
                prev.map((lead) => (lead.id === id ? { ...lead, contact_status: newStatus } : lead))
            );
        } catch (error) {
            console.error('Status update failed', error);
        }
    };

    const getScoreBadge = (score) => {
        if (score === undefined || score === null) return <Badge variant="outline">N/A</Badge>;
        if (score <= 2) return <Badge variant="danger">HOT ({score}/5)</Badge>;
        if (score <= 4) return <Badge variant="warning">WARM ({score}/5)</Badge>;
        return <Badge variant="success">COLD ({score}/5)</Badge>;
    };

    if (loading) {
        return <div className="flex justify-center p-8"><Loader2 className="animate-spin h-8 w-8" /></div>;
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">Leads</h2>
                    <p className="text-muted-foreground">Manage and track your audits.</p>
                </div>
                <Button onClick={fetchLeads} variant="outline" size="sm">
                    Refresh
                </Button>
            </div>

            <div className="grid gap-4">
                {leads.map((lead) => (
                    <Card key={lead.id} className="overflow-hidden">
                        <div className="flex flex-col md:flex-row">
                            <div className="p-6 flex-1 space-y-4">
                                <div className="flex justify-between items-start">
                                    <div>
                                        <h3 className="text-xl font-bold hover:underline cursor-pointer">
                                            {lead.name}
                                        </h3>
                                        <p className="text-sm text-muted-foreground flex items-center gap-2">
                                            {lead.address}
                                        </p>
                                        <a
                                            href={lead.website_url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="text-xs text-blue-500 hover:underline flex items-center gap-1 mt-1"
                                        >
                                            {lead.website_url} <ExternalLink className="h-3 w-3" />
                                        </a>
                                    </div>
                                    <div className="flex flex-col items-end gap-2">
                                        {lead.audit ? (
                                            getScoreBadge(lead.audit.score)
                                        ) : (
                                            <Badge variant="outline">Not Audited</Badge>
                                        )}
                                    </div>
                                </div>

                                {lead.audit && (
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-muted/30 p-4 rounded-lg text-sm">
                                        <div className="flex items-center gap-2">
                                            {lead.audit.has_schema ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
                                            <span>Schema</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {lead.audit.has_sameas ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
                                            <span>sameAs</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {lead.audit.category_aligned ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
                                            <span>Category</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {lead.audit.nap_consistent ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
                                            <span>NAP</span>
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className="p-6 bg-muted/50 border-l flex flex-col justify-center space-y-4 min-w-[200px]">
                                <div className="space-y-2">
                                    <span className="text-xs font-semibold text-muted-foreground uppercase">Contact Status</span>
                                    <select
                                        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                        value={lead.contact_status}
                                        onChange={(e) => handleStatusChange(lead.id, e.target.value)}
                                    >
                                        <option value="NEW">New</option>
                                        <option value="CONTACTED">Contacted</option>
                                        <option value="REPLIED">Replied</option>
                                        <option value="CLOSED">Closed</option>
                                    </select>
                                </div>

                                {!lead.audit && (
                                    <Button
                                        size="sm"
                                        onClick={() => handleAudit(lead.id)}
                                        disabled={auditLoading[lead.id]}
                                    >
                                        {auditLoading[lead.id] ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PlayCircle className="mr-2 h-4 w-4" />}
                                        Run Audit
                                    </Button>
                                )}
                            </div>
                        </div>
                    </Card>
                ))}

                {leads.length === 0 && (
                    <div className="text-center p-12 text-muted-foreground border-2 border-dashed rounded-lg">
                        No leads found. Go to Discovery to find some!
                    </div>
                )}
            </div>
        </div>
    );
}
