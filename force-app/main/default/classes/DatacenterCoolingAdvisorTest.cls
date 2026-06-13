@isTest
private class DatacenterCoolingAdvisorTest {
    @isTest
    static void returnsRankedCoolingPlan() {
        Test.startTest();
        DatacenterCoolingAdvisor.CoolingPlan plan = DatacenterCoolingAdvisor.evaluateCoolingPlan(
            520,
            68,
            83,
            90,
            46,
            64,
            0.14,
            80.6,
            'CRAH'
        );
        Test.stopTest();

        System.assertNotEquals(null, plan, 'Expected a cooling plan.');
        System.assertNotEquals(null, plan.recommendedAction, 'Expected a recommended action.');
        System.assertEquals(5, plan.actionScores.size(), 'Expected each candidate action to be scored.');
        System.assertEquals(6, plan.forecast.size(), 'Expected a six-hour forecast.');
        System.assert(plan.confidence >= 55, 'Confidence should be bounded to an operator-friendly range.');
        System.assert(plan.pue > 1, 'PUE should include cooling overhead.');
        System.assert(
            plan.actionScores[0].qValue >= plan.actionScores[1].qValue,
            'Action scores should be sorted from highest to lowest reward.'
        );
    }

    @isTest
    static void normalizesUnsafeInputs() {
        DatacenterCoolingAdvisor.CoolingPlan plan = DatacenterCoolingAdvisor.evaluateCoolingPlan(
            null,
            120,
            40,
            1,
            90,
            140,
            -1,
            95,
            'unknown'
        );

        System.assertNotEquals(null, plan.recommendedAction, 'Defaults and bounds should produce a recommendation.');
        System.assertEquals(5, plan.actionScores.size(), 'All candidate actions should still be considered.');
        System.assert(plan.riskScore <= 100, 'Risk score should be capped.');
        System.assert(plan.costPerHour > 0, 'Energy cost should use a safe positive price.');
        System.assert(!plan.alerts.isEmpty(), 'Operators should receive at least one status message.');
    }
}
