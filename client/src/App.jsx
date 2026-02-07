import React, { useState } from 'react';
import Discovery from './pages/Discovery';
import Leads from './pages/Leads';
import { cn } from './lib/utils';
import { LayoutDashboard, Search } from 'lucide-react';

function App() {
  const [activeTab, setActiveTab] = useState('leads');

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Sidebar / Navigation */}
      <div className="flex h-screen flex-col md:flex-row overflow-hidden">
        <aside className="w-full md:w-64 border-r bg-muted/40 p-4 hidden md:block">
          <div className="mb-8 flex items-center gap-2 px-2 font-bold text-xl">
            <span className="h-6 w-6 rounded-full bg-primary" />
            Schema Audit
          </div>
          <nav className="space-y-2">
            <Button
              variant={activeTab === 'discovery' ? 'secondary' : 'ghost'}
              className="w-full justify-start"
              onClick={() => setActiveTab('discovery')}
            >
              <Search className="mr-2 h-4 w-4" />
              Discovery
            </Button>
            <Button
              variant={activeTab === 'leads' ? 'secondary' : 'ghost'}
              className="w-full justify-start"
              onClick={() => setActiveTab('leads')}
            >
              <LayoutDashboard className="mr-2 h-4 w-4" />
              Leads & Audits
            </Button>
          </nav>
        </aside>

        {/* Mobile Nav (Simple top bar) */}
        <div className="md:hidden border-b p-4 flex gap-4 overflow-x-auto">
          <Button
            variant={activeTab === 'discovery' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab('discovery')}
          >
            Discovery
          </Button>
          <Button
            variant={activeTab === 'leads' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab('leads')}
          >
            Leads
          </Button>
        </div>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto p-8">
          <div className="mx-auto max-w-5xl">
            {activeTab === 'discovery' && <Discovery />}
            {activeTab === 'leads' && <Leads />}
          </div>
        </main>
      </div>
    </div>
  );
}

// Simple internal Button component duplication or import? 
// I should import from components/ui/button.
import { Button } from './components/ui/button';

export default App;
