import { LightningElement, track } from 'lwc';
import evaluateCoolingPlan from '@salesforce/apex/DatacenterCoolingAdvisor.evaluateCoolingPlan';

export default class DatacenterCoolingTool extends LightningElement {
    @track form = {
        rackLoadKw: 480,
        supplyTempF: 68,
        returnTempF: 82,
        airflowKcfm: 85,
        humidityPct: 45,
        outsideAirTempF: 72,
        energyPricePerKwh: 0.12,
        maxInletTempF: 80.6,
        coolingMode: 'CRAC'
    };

    @track result;
    isLoading = false;
    errorMessage;

    get modeOptions() {
        return [
            { label: 'CRAC - compressor based', value: 'CRAC' },
            { label: 'CRAH - chilled water', value: 'CRAH' }
        ];
    }

    get hasResult() {
        return this.result !== undefined && this.result !== null;
    }

    get alertItems() {
        if (!this.result || !this.result.alerts) {
            return [];
        }
        return this.result.alerts.map((message, index) => ({
            id: `alert-${index}`,
            message
        }));
    }

    connectedCallback() {
        this.runPolicy();
    }

    handleInputChange(event) {
        const fieldName = event.target.name;
        const value = event.detail.value;
        this.form = {
            ...this.form,
            [fieldName]: fieldName === 'coolingMode' ? value : Number(value)
        };
    }

    runPolicy() {
        this.isLoading = true;
        this.errorMessage = undefined;

        evaluateCoolingPlan({ ...this.form })
            .then((plan) => {
                this.result = plan;
                this.isLoading = false;
            })
            .catch((error) => {
                const body = error && error.body ? error.body : {};
                this.errorMessage =
                    body.message || (error && error.message) || 'Unable to evaluate the cooling policy.';
                this.isLoading = false;
            });
    }
}
