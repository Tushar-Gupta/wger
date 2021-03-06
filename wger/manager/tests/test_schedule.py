# This file is part of wger Workout Manager.
#
# wger Workout Manager is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# wger Workout Manager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License

import six
import logging
import datetime

from django.core.urlresolvers import reverse
from django.contrib.auth.models import User

from wger.core.tests import api_base_test
from wger.manager.models import Schedule
from wger.manager.models import ScheduleStep
from wger.manager.models import Workout
from wger.manager.tests.testcase import STATUS_CODES_FAIL
from wger.manager.tests.testcase import WorkoutManagerTestCase
from wger.manager.tests.testcase import WorkoutManagerDeleteTestCase
from wger.manager.tests.testcase import WorkoutManagerEditTestCase
from wger.manager.tests.testcase import WorkoutManagerAddTestCase
from wger.utils.helpers import make_token


logger = logging.getLogger('wger.custom')


class CreateScheduleTestCase(WorkoutManagerAddTestCase):
    '''
    Tests adding a schedule
    '''

    object_class = Schedule
    url = 'manager:schedule:add'
    user_success = 'test'
    user_fail = False
    data = {'name': 'My cool schedule',
            'start_date': datetime.date.today(),
            'is_active': True,
            'is_loop': True}


class DeleteScheduleTestCase(WorkoutManagerDeleteTestCase):
    '''
    Tests deleting a schedule
    '''

    object_class = Schedule
    url = 'manager:schedule:delete'
    pk = 1
    user_success = 'test'
    user_fail = 'admin'


class EditScheduleTestCase(WorkoutManagerEditTestCase):
    '''
    Tests editing a schedule
    '''

    object_class = Schedule
    url = 'manager:schedule:edit'
    pk = 3
    data = {'name': 'An updated name',
            'start_date': datetime.date.today(),
            'is_active': True,
            'is_loop': True}


class ScheduleTestCase(WorkoutManagerTestCase):
    '''
    Other tests
    '''

    def schedule_detail_page(self, fail=False):
        '''
        Helper function
        '''

        response = self.client.get(reverse('manager:schedule:view', kwargs={'pk': 2}))
        if fail:
            self.assertIn(response.status_code, STATUS_CODES_FAIL)
        else:
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'This schedule is a loop')

            schedule = Schedule.objects.get(pk=2)
            schedule.is_loop = False
            schedule.save()

            response = self.client.get(reverse('manager:schedule:view', kwargs={'pk': 2}))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'This schedule is a loop')

    def test_schedule_detail_page_owner(self):
        '''
        Tests the schedule detail page as the owning user
        '''

        self.user_login()
        self.schedule_detail_page()

    def test_schedule_detail_page_other(self):
        '''
        Tests the schedule detail page as a different user
        '''

        self.user_login('test')
        self.schedule_detail_page(fail=True)

    def test_schedule_overview(self):
        '''
        Tests the schedule overview
        '''
        self.user_login()

        response = self.client.get(reverse('manager:schedule:overview'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['schedules']), 3)
        self.assertTrue(response.context['schedules'][0].is_active)
        if self.is_mobile:
            self.assertInHTML('<span class="label label-primary pull-right"><em>active</em></span>',
                              six.text_type(response.content))
        else:
            self.assertInHTML('<span class="label label-primary">active</span>',
                              six.text_type(response.content))
        schedule = Schedule.objects.get(pk=4)
        schedule.is_active = False
        schedule.save()

        response = self.client.get(reverse('manager:schedule:overview'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['schedules']), 3)
        for i in range(0, 3):
            self.assertFalse(response.context['schedules'][i].is_active)
        if self.is_mobile:
            self.assertNotContains(response, '<p class="ui-li-aside"><em>active</em></p>')
        else:
            self.assertNotContains(response, '<span class="label label-primary">active</span>')

    def test_schedule_active(self):
        '''
        Tests that only one schedule can be active at a time (per user)
        '''
        def get_schedules():
            schedule1 = Schedule.objects.get(pk=2)
            schedule2 = Schedule.objects.get(pk=3)
            schedule3 = Schedule.objects.get(pk=4)

            return (schedule1, schedule2, schedule3)

        self.user_login()
        (schedule1, schedule2, schedule3) = get_schedules()
        self.assertTrue(schedule3.is_active)

        schedule1.is_active = True
        schedule1.save()
        (schedule1, schedule2, schedule3) = get_schedules()
        self.assertTrue(schedule1.is_active)
        self.assertFalse(schedule2.is_active)
        self.assertFalse(schedule3.is_active)

        schedule2.is_active = True
        schedule2.save()
        (schedule1, schedule2, schedule3) = get_schedules()
        self.assertFalse(schedule1.is_active)
        self.assertTrue(schedule2.is_active)
        self.assertFalse(schedule3.is_active)

    def start_schedule(self, fail=False):
        '''
        Helper function
        '''

        schedule = Schedule.objects.get(pk=2)
        self.assertFalse(schedule.is_active)
        self.assertNotEqual(schedule.start_date, datetime.date.today())

        response = self.client.get(reverse('manager:schedule:start', kwargs={'pk': 2}))
        schedule = Schedule.objects.get(pk=2)
        if fail:
            self.assertIn(response.status_code, STATUS_CODES_FAIL)
            self.assertFalse(schedule.is_active)
            self.assertNotEqual(schedule.start_date, datetime.date.today())
        else:
            self.assertEqual(response.status_code, 302)
            self.assertTrue(schedule.is_active)
            self.assertEqual(schedule.start_date, datetime.date.today())

    def test_start_schedule_owner(self):
        '''
        Tests starting a schedule as the owning user
        '''

        self.user_login()
        self.start_schedule()

    def test_start_schedule_other(self):
        '''
        Tests starting a schedule as a different user
        '''

        self.user_login('test')
        self.start_schedule(fail=True)

    def test_start_schedule_anonymous(self):
        '''
        Tests starting a schedule as a logged out user
        '''

        self.start_schedule(fail=True)


class ScheduleEndDateTestCase(WorkoutManagerTestCase):
    '''
    Test the schedule's get_end_date method
    '''

    def test_loop_schedule(self):
        '''
        Loop schedules have no end date
        '''
        schedule = Schedule.objects.get(pk=2)
        self.assertTrue(schedule.is_loop)
        self.assertFalse(schedule.get_end_date())

    def test_calculate(self):
        '''
        Test the actual calculation

        Steps: 3, 5 and 2 weeks, starting on the 2013-04-21
        '''
        schedule = Schedule.objects.get(pk=2)
        schedule.is_loop = False
        schedule.save()
        self.assertEqual(schedule.get_end_date(), datetime.date(2013, 6, 30))

    def test_empty_schedule(self):
        '''
        Test the end date with an empty schedule
        '''
        schedule = Schedule.objects.get(pk=3)
        self.assertEqual(schedule.get_end_date(), schedule.start_date)


class ScheduleModelTestCase(WorkoutManagerTestCase):
    '''
    Tests the model methods
    '''

    def delete_objects(self, user):
        '''
        Helper function
        '''

        Workout.objects.filter(user=user).delete()
        Schedule.objects.filter(user=user).delete()

    def create_schedule(self, user, start_date=datetime.date.today(), is_loop=False):
        '''
        Helper function
        '''

        schedule = Schedule()
        schedule.user = user
        schedule.name = 'temp'
        schedule.is_active = True
        schedule.start_date = start_date
        schedule.is_loop = is_loop
        schedule.save()
        return schedule

    def create_workout(self, user):
        '''
        Helper function
        '''

        workout = Workout()
        workout.user = user
        workout.save()
        return workout

    def test_get_workout_steps_test_1(self):
        '''
        Test with no workouts and no schedule steps
        '''
        self.user_login('test')
        user = User.objects.get(pk=2)
        self.delete_objects(user)

        schedule = self.create_schedule(user)
        self.assertFalse(schedule.get_current_scheduled_workout())

    def test_get_workout_steps_test_2(self):
        '''
        Test with one schedule step
        '''
        self.user_login('test')
        user = User.objects.get(pk=2)
        self.delete_objects(user)

        schedule = self.create_schedule(user)
        workout = self.create_workout(user)
        step = ScheduleStep()
        step.schedule = schedule
        step.workout = workout
        step.duration = 3
        step.save()
        self.assertEqual(schedule.get_current_scheduled_workout().workout, workout)

    def test_get_workout_steps_test_3(self):
        '''
        Test with 3 steps
        '''
        self.user_login('test')
        user = User.objects.get(pk=2)
        self.delete_objects(user)

        start_date = datetime.date.today() - datetime.timedelta(weeks=4)
        schedule = self.create_schedule(user, start_date=start_date)
        workout = self.create_workout(user)
        step = ScheduleStep()
        step.schedule = schedule
        step.workout = workout
        step.duration = 3
        step.order = 1
        step.save()

        workout2 = self.create_workout(user)
        step2 = ScheduleStep()
        step2.schedule = schedule
        step2.workout = workout2
        step2.duration = 1
        step2.order = 2
        step2.save()

        workout3 = self.create_workout(user)
        step3 = ScheduleStep()
        step3.schedule = schedule
        step3.workout = workout3
        step3.duration = 2
        step3.order = 3
        step3.save()
        self.assertEqual(schedule.get_current_scheduled_workout().workout, workout2)

    def test_get_workout_steps_test_4(self):
        '''
        Test with 3 steps. Start is too far in the past, schedule ist not a loop
        '''
        self.user_login('test')
        user = User.objects.get(pk=2)
        self.delete_objects(user)

        start_date = datetime.date.today() - datetime.timedelta(weeks=7)
        schedule = self.create_schedule(user, start_date=start_date)
        workout = self.create_workout(user)
        step = ScheduleStep()
        step.schedule = schedule
        step.workout = workout
        step.duration = 3
        step.order = 1
        step.save()

        workout2 = self.create_workout(user)
        step2 = ScheduleStep()
        step2.schedule = schedule
        step2.workout = workout2
        step2.duration = 1
        step2.order = 2
        step2.save()

        workout3 = self.create_workout(user)
        step3 = ScheduleStep()
        step3.schedule = schedule
        step3.workout = workout3
        step3.duration = 2
        step3.order = 3
        step3.save()
        self.assertFalse(schedule.get_current_scheduled_workout())

    def test_get_workout_steps_test_5(self):
        '''
        Test with 3 steps. Start is too far in the past but schedule is a loop
        '''
        self.user_login('test')
        user = User.objects.get(pk=2)
        self.delete_objects(user)

        start_date = datetime.date.today() - datetime.timedelta(weeks=7)
        schedule = self.create_schedule(user, start_date=start_date, is_loop=True)
        workout = self.create_workout(user)
        step = ScheduleStep()
        step.schedule = schedule
        step.workout = workout
        step.duration = 3
        step.order = 1
        step.save()

        workout2 = self.create_workout(user)
        step2 = ScheduleStep()
        step2.schedule = schedule
        step2.workout = workout2
        step2.duration = 1
        step2.order = 2
        step2.save()

        workout3 = self.create_workout(user)
        step3 = ScheduleStep()
        step3.schedule = schedule
        step3.workout = workout3
        step3.duration = 2
        step3.order = 3
        step3.save()
        self.assertTrue(schedule.get_current_scheduled_workout().workout, workout)


class SchedulePdfLogExportTestCase(WorkoutManagerTestCase):
    '''
    Test exporting a schedule as a pdf
    '''

    def export_pdf_token(self):
        '''
        Helper function to test exporting a workout as a pdf using tokens
        '''

        user = User.objects.get(username='test')
        uid, token = make_token(user)
        response = self.client.get(reverse('manager:schedule:pdf', kwargs={'pk': 1,
                                                                           'uidb64': uid,
                                                                           'token': token}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'],
                         'attachment; filename=Schedule-1-log.pdf')

        # Approximate size only
        self.assertGreater(int(response['Content-Length']), 31000)
        self.assertLess(int(response['Content-Length']), 35000)

    def export_pdf(self, fail=False):
        '''
        Helper function to test exporting a workout as a pdf
        '''

        response = self.client.get(reverse('manager:schedule:pdf', kwargs={'pk': 1}))

        if fail:
            self.assertIn(response.status_code, (404, 302))
        else:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertEqual(response['Content-Disposition'],
                             'attachment; filename=Schedule-1-log.pdf')

            # Approximate size only
            self.assertGreater(int(response['Content-Length']), 31000)
            self.assertLess(int(response['Content-Length']), 35000)

    def test_export_pdf_anonymous(self):
        '''
        Tests exporting a workout as a pdf as an anonymous user
        '''

        self.export_pdf(fail=True)
        self.export_pdf_token()

    def test_export_pdf_owner(self):
        '''
        Tests exporting a workout as a pdf as the owner user
        '''

        self.user_login('test')
        self.export_pdf(fail=False)
        self.export_pdf_token()

    def test_export_pdf_other(self):
        '''
        Tests exporting a workout as a pdf as a logged user not owning the data
        '''

        self.user_login('admin')
        self.export_pdf(fail=True)
        self.export_pdf_token()


class ScheduleApiTestCase(api_base_test.ApiBaseResourceTestCase):
    '''
    Tests the schedule overview resource
    '''
    pk = 1
    resource = Schedule
    private_resource = True
    data = {'name': 'An updated name',
            'start_date': datetime.date.today(),
            'is_active': True,
            'is_loop': True}
